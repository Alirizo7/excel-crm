import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import DebtForm, PaymentForm, CancelPaymentForm, RevisionForm, DateFilters
from .models import Counterparty, PartnerBalance, DebtPayment
from .services.changes import workspace_transaction, partner_for, snapshot, check_revision, changed, log_change, set_record_active, change_history
from .services.debts import debt_rows, debt_stats, record_payment, cancel_payment


def actor(request):
    return request.user.get_username() if request.user.is_authenticated else ''


def partners(request):
    rows = debt_rows().filter(active=True)
    stats = debt_stats(rows)
    stats['paid'] = DebtPayment.objects.filter(cancelled_at=None).aggregate(total=Sum('amount'))['total'] or 0
    stats['paid_in'] = DebtPayment.objects.filter(cancelled_at=None, debt__balance__gt=0).aggregate(total=Sum('amount'))['total'] or 0
    stats['paid_out'] = DebtPayment.objects.filter(cancelled_at=None, debt__balance__lt=0).aggregate(total=Sum('amount'))['total'] or 0
    status = request.GET.get('status', 'open')
    if status == 'deleted':
        rows = debt_rows().filter(deleted_at__isnull=False, archived_at=None)
    elif status == 'closed':
        rows = rows.filter(amount_left=0)
    elif status == 'overdue':
        rows = rows.filter(amount_left__gt=0, due_date__lt=timezone.localdate())
    elif status != 'all':
        rows = rows.filter(amount_left__gt=0)
        status = 'open'
    if request.GET.get('q'):
        rows = rows.filter(Q(name__icontains=request.GET['q']) | Q(note__icontains=request.GET['q']))
    if request.GET.get('side') == 'receivable':
        rows = rows.filter(balance__gt=0)
    elif request.GET.get('side') == 'payable':
        rows = rows.filter(balance__lt=0)
    return render(request, 'ledger/partners.html', {'nav': 'partners', 'title': _('Долги'),
        'page': Paginator(rows.order_by('-amount_left', 'name', 'pk'), 25).get_page(request.GET.get('page')),
        'stats': stats, 'status': status, 'recent_payments': DebtPayment.objects.select_related('debt__counterparty').all()[:6]})


def partner_detail(request, pk):
    partner = get_object_or_404(Counterparty, pk=pk)
    rows = debt_rows().filter(counterparty=partner, active=True)
    payments = DebtPayment.objects.filter(debt__counterparty=partner).select_related('debt')
    filters = DateFilters(request.GET)
    if filters.is_valid():
        if filters.cleaned_data.get('start'):
            payments = payments.filter(date__gte=filters.cleaned_data['start'])
        if filters.cleaned_data.get('end'):
            payments = payments.filter(date__lte=filters.cleaned_data['end'])
    else:
        payments = payments.none()
    paid = payments.filter(cancelled_at=None).aggregate(total=Sum('amount'))['total'] or 0
    return render(request, 'ledger/partner_detail.html', {'nav': 'partners', 'title': partner.name, 'partner': partner,
        'debts': rows, 'stats': debt_stats(rows), 'paid': paid, 'filters': filters,
        'page': Paginator(payments, 20).get_page(request.GET.get('page')),
        'archived_debts': debt_rows().filter(counterparty=partner, active=False)})


def debt_detail(request, pk):
    debt = get_object_or_404(debt_rows(), pk=pk)
    return render(request, 'ledger/debt_detail.html', {'nav': 'partners', 'title': _('Карточка долга'), 'debt': debt,
        'payments': debt.payments.all(), 'changes': change_history('partners', pk),
        'can_restore': bool(debt.deleted_at) and not debt.archived_at})


def debt_form(request, pk=None):
    debt = get_object_or_404(PartnerBalance, pk=pk, active=True) if pk else PartnerBalance()
    initial = {'name': request.GET.get('name', '')} if not pk else {}
    form = DebtForm(instance=debt, initial=initial)
    if request.method == 'POST':
        with workspace_transaction():
            debt = get_object_or_404(PartnerBalance, pk=pk, active=True) if pk else PartnerBalance()
            before = snapshot(debt) if pk else {}
            form = DebtForm(request.POST, instance=debt)
            if form.is_valid():
                try:
                    check_revision(debt, form.cleaned_data.get('revision') or 0)
                    debt.balance = form.cleaned_data['principal'] * (1 if form.cleaned_data['side'] == 'receivable' else -1)
                    debt.counterparty = partner_for(debt.name)
                    changed(debt)
                    debt.full_clean()
                    debt.save()
                    log_change(debt, 'partners', before, 'edit' if pk else 'create', actor(request))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, _('Долг сохранён. Остаток пересчитан.'))
                    return redirect('debt_detail', pk=debt.pk)
    return render(request, 'ledger/debt_form.html', {'nav': 'partners', 'title': _('Редактирование долга') if pk else _('Новый долг'), 'form': form, 'debt': debt})


@require_POST
def debt_toggle(request, pk, restore=False):
    form = RevisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _('Обновите страницу и повторите действие.'))
        return redirect('debt_detail', pk=pk)
    with workspace_transaction():
        debt = get_object_or_404(PartnerBalance.objects.select_related('batch'), pk=pk, active=not restore)
        try:
            set_record_active(debt, 'partners', restore, form.cleaned_data['revision'], actor(request))
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        else:
            messages.success(request, _('Запись восстановлена.') if restore else _('Долг удалён из текущего учёта.'))
    return redirect('debt_detail', pk=pk)


def payment_new(request, pk):
    debt = get_object_or_404(debt_rows(), pk=pk)
    form = PaymentForm(request.POST or None, initial={'revision': debt.revision, 'request_key': uuid.uuid4(),
                                                     'date': timezone.localdate(), 'amount': debt.outstanding})
    if request.method == 'POST' and form.is_valid():
        try:
            payment, created = record_payment(pk, **form.cleaned_data, actor=actor(request))
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _('Погашение записано. Остаток долга обновлён.') if created else _('Эта оплата уже записана. Повтор не создан.'))
            return redirect('partners')
    return render(request, 'ledger/payment_form.html', {'nav': 'partners', 'title': _('Внести оплату'), 'debt': debt, 'form': form})


def payment_cancel(request, pk):
    payment = get_object_or_404(DebtPayment.objects.select_related('debt__counterparty'), pk=pk)
    form = CancelPaymentForm(request.POST or None, initial={'revision': payment.debt.revision})
    if request.method == 'POST' and form.is_valid():
        try:
            cancel_payment(pk, reason=form.cleaned_data['reason'], revision=form.cleaned_data['revision'], actor=actor(request))
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _('Оплата отменена. Сумма возвращена в остаток долга.'))
            return redirect('debt_detail', pk=payment.debt_id)
    return render(request, 'ledger/payment_cancel.html', {'nav': 'partners', 'title': _('Отмена оплаты'), 'payment': payment, 'form': form})
