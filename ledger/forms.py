from django.utils.translation import gettext_noop
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .models import Operation, Delivery


class WorkspaceLoginForm(AuthenticationForm):
    error_messages = {
        'invalid_login': _('Проверьте имя пользователя и пароль. Учитывайте регистр букв.'),
        'inactive': _('Эта учётная запись отключена.'),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = _('Имя пользователя')
        self.fields['password'].label = _('Пароль')


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
    class Meta:
        model = Operation
        fields = ['date', 'kind', 'amount', 'description', 'category', 'partner']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'description': forms.Textarea(attrs={'rows': 3}),
                   'category': forms.Select(choices=[(x,_(x)) for x in [gettext_noop('Металл'), gettext_noop('Транспорт'), gettext_noop('Расчёты с партнёрами'), gettext_noop('Хозяйственные расходы'), gettext_noop('Прочее')]])}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].required = True

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount == 0:
            raise ValidationError(_('Сумма операции не может быть нулевой.'))
        return amount


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ['date', 'direction', 'partner', 'vehicle', 'gross', 'tare', 'discount', 'price', 'notes']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].required = True

    def clean(self):
        data = super().clean()
        if data.get('gross') is not None and data.get('tare') is not None and data['gross'] < data['tare']:
            self.add_error('tare', _('Тара не может превышать брутто.'))
        return data
