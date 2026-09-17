from django.utils.translation import gettext_noop
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .models import Operation, Delivery, PartnerBalance
from django.utils import timezone
from decimal import Decimal


class WorkspaceLoginForm(AuthenticationForm):
    error_messages = {
        'invalid_login': _('Проверьте имя пользователя и пароль. Учитывайте регистр букв.'),
        'inactive': _('Эта учётная запись отключена.'),
        'inactive_company': _('Доступ компании временно приостановлен. Обратитесь к администратору.'),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = _('Имя пользователя')
        self.fields['password'].label = _('Пароль')

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        membership = getattr(user, 'workspace_membership', None)
        if membership and not membership.workspace.is_active and not user.is_superuser:
            raise ValidationError(
                self.error_messages['inactive_company'],
                code='inactive_company',
            )


class ImportForm(forms.Form):
    file = forms.FileField(label=_('Файл Excel'), widget=forms.FileInput(attrs={'accept': '.xlsx', 'id': 'excel-file'}))
    report_date = forms.DateField(label=_('Дата снимка'), required=False, widget=forms.DateInput(attrs={'type': 'date'}),
                                  help_text=_('Если не указать, возьмём дату из имени файла. Даты самих операций не изменятся.'))


class DateFilters(forms.Form):
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['start'] > data['end']:
            raise ValidationError(_('Дата начала должна быть раньше даты окончания.'))
        return data


class OperationForm(forms.ModelForm):
    revision = forms.IntegerField(widget=forms.HiddenInput, required=False, initial=0, min_value=0)
    class Meta:
        model = Operation
        fields = ['date', 'kind', 'amount', 'description', 'category', 'partner']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'description': forms.Textarea(attrs={'rows': 3}),
                   'category': forms.Select(choices=[(x,_(x)) for x in [gettext_noop('Металл'), gettext_noop('Транспорт'), gettext_noop('Расчёты с партнёрами'), gettext_noop('Хозяйственные расходы'), gettext_noop('Прочее')]])}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].required = not bool(self.instance.batch_id)
        self.initial['revision'] = self.instance.revision

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount == 0:
            raise ValidationError(_('Сумма операции не может быть нулевой.'))
        return amount


class DeliveryForm(forms.ModelForm):
    revision = forms.IntegerField(widget=forms.HiddenInput, required=False, initial=0, min_value=0)
    class Meta:
        model = Delivery
        fields = ['date', 'direction', 'partner', 'vehicle', 'gross', 'tare', 'discount', 'price', 'notes']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].required = not bool(self.instance.batch_id)
        self.initial['revision'] = self.instance.revision

    def clean(self):
        data = super().clean()
        if data.get('gross') is not None and data.get('tare') is not None and data['gross'] < data['tare']:
            self.add_error('tare', _('Тара не может превышать брутто.'))
        return data


class DebtForm(forms.ModelForm):
    revision = forms.IntegerField(widget=forms.HiddenInput, required=False, initial=0, min_value=0)
    side = forms.ChoiceField(label=_('Кто должен'), choices=[('receivable', _('Нам должны')), ('payable', _('Мы должны'))])
    principal = forms.DecimalField(label=_('Полная сумма долга, UZS'), max_digits=20, decimal_places=2, min_value=0,
                                  help_text=_('Сумма до погашений. Внесённые оплаты вычитаются автоматически.'))

    class Meta:
        model = PartnerBalance
        fields = ['name', 'side', 'principal', 'due_date', 'note']
        labels = {'name': _('Контрагент'), 'note': _('Основание долга / примечание')}
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'note': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['revision'] = self.instance.revision
        if self.instance.pk:
            self.initial.update(side='receivable' if self.instance.balance >= 0 else 'payable', principal=abs(self.instance.balance))

    def clean(self):
        data = super().clean()
        amount = data.get('principal')
        if amount is not None and amount < self.instance.paid_amount:
            self.add_error('principal', _('Полная сумма долга не может быть меньше уже погашенной суммы.'))
        if self.instance.pk and self.instance.paid_amount:
            # Compare names without creating a counterparty during validation.
            if data.get('name') != self.instance.name or data.get('side') != ('receivable' if self.instance.balance >= 0 else 'payable'):
                raise ValidationError(_('У долга с оплатами нельзя менять контрагента и сторону долга.'))
        return data


class PaymentForm(forms.Form):
    revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    date = forms.DateField(label=_('Дата оплаты'), widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    amount = forms.DecimalField(label=_('Сумма оплаты, UZS'), max_digits=20, decimal_places=2, min_value=Decimal('.01'))
    note = forms.CharField(label=_('Примечание'), required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 3}))

    def clean_date(self):
        date = self.cleaned_data['date']
        if date > timezone.localdate():
            raise ValidationError(_('Дата фактической оплаты не может быть в будущем.'))
        return date


class RevisionForm(forms.Form):
    revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)


class CancelPaymentForm(RevisionForm):
    reason = forms.CharField(label=_('Причина отмены'), max_length=500, widget=forms.Textarea(attrs={'rows': 3}))
