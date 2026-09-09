from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, F, Case, When, DecimalField, ExpressionWrapper
from django.db.models.functions import Abs
from django.utils import timezone
from django.utils.translation import gettext

from ledger.models import DebtPayment, PartnerBalance
from .changes import workspace_transaction, check_revision, snapshot, changed, log_change


def debt_rows():
    money = DecimalField(max_digits=20, decimal_places=2)
    return PartnerBalance.objects.select_related('counterparty', 'batch').annotate(
        amount_left=ExpressionWrapper(Abs('balance') - F('paid_amount'), output_field=money),
        signed_left=Case(When(balance__gte=0, then=F('balance') - F('paid_amount')),
                         default=F('balance') + F('paid_amount'), output_field=money))


def debt_stats(rows):
    values = rows.aggregate(
        receivable=Sum('amount_left', filter=Q(balance__gt=0)),
        payable=Sum('amount_left', filter=Q(balance__lt=0)),
        overdue=Sum('amount_left', filter=Q(due_date__lt=timezone.localdate(), amount_left__gt=0)),
    )
    result = {key: value or Decimal('0') for key, value in values.items()}
    result['net'] = result['receivable'] - result['payable']
    result['open_count'] = rows.filter(amount_left__gt=0).count()
    result['closed_count'] = rows.filter(amount_left=0).count()
    return result


@workspace_transaction()
def record_payment(debt_id, *, amount, date, note, request_key, revision, actor):
    previous = DebtPayment.objects.filter(request_key=request_key).first()
    if previous:
        if previous.debt_id != debt_id or previous.amount != amount or previous.date != date or previous.note != note:
            raise ValidationError(gettext('Этот запрос уже использован для другой оплаты. Обновите страницу.'))
        return previous, False
    debt = PartnerBalance.objects.get(pk=debt_id)
    check_revision(debt, revision)
    if not debt.active:
        raise ValidationError(gettext('Долг больше не находится в текущем учёте.'))
    if amount <= 0 or amount > debt.outstanding:
        raise ValidationError(gettext('Сумма оплаты должна быть больше нуля и не превышать остаток долга.'))
    if date > timezone.localdate():
        raise ValidationError(gettext('Дата фактической оплаты не может быть в будущем.'))
    before = snapshot(debt)
    payment = DebtPayment(debt=debt, amount=amount, date=date, note=note, request_key=request_key, actor=actor)
    payment.full_clean()
    payment.save()
    debt.paid_amount += amount
    changed(debt)
    debt.save()
    log_change(debt, 'partners', before, 'payment', actor)
    return payment, True


@workspace_transaction()
def cancel_payment(payment_id, *, reason, revision, actor):
    payment = DebtPayment.objects.select_related('debt').get(pk=payment_id)
    if payment.cancelled_at:
        return False
    debt = payment.debt
    if not debt.active:
        raise ValidationError(gettext('Оплата относится к архивному долгу. Его история доступна только для просмотра.'))
    check_revision(debt, revision)
    if not reason.strip():
        raise ValidationError(gettext('Укажите причину отмены оплаты.'))
    before = snapshot(debt)
    debt.paid_amount -= payment.amount
    changed(debt)
    debt.save()
    payment.cancelled_at = timezone.now()
    payment.cancel_reason = reason.strip()
    payment.cancelled_by = actor
    payment.save(update_fields=['cancelled_at', 'cancel_reason', 'cancelled_by'])
    log_change(debt, 'partners', before, 'cancel_payment', actor)
    return True
