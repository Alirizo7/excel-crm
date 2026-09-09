from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
import unicodedata

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext, gettext_noop

from ledger.models import Activity, Counterparty, RecordChange, WorkspaceState


@contextmanager
def workspace_transaction():
    with transaction.atomic():
        # First query is a write: obtains the SQLite writer lock before reading
        # a balance. PostgreSQL also locks this row until the transaction ends.
        if not WorkspaceState.objects.filter(pk=1).update(revision=F('revision') + 1):
            raise RuntimeError('WorkspaceState is missing. Run migrations.')
        yield


def partner_for(name):
    name = ' '.join(name.split())
    key = unicodedata.normalize('NFKC', name).casefold()
    return Counterparty.objects.get_or_create(key=key, defaults={'name': name})[0]


def snapshot(record):
    values = {}
    for field in record._meta.concrete_fields:
        value = field.value_from_object(record)
        if isinstance(value, (Decimal, date, datetime)):
            value = str(value)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        values[field.name] = value
    return values


def check_revision(record, revision):
    if record.revision != revision:
        raise ValidationError(gettext('Запись уже изменена. Обновите страницу и повторите действие.'))


def log_change(record, kind, before, action, actor):
    RecordChange.objects.create(kind=kind, record_id=record.pk, before=before, after=snapshot(record), action=action, actor=actor)
    title = {'edit': gettext_noop('Запись изменена'), 'create': gettext_noop('Запись добавлена'),
             'delete': gettext_noop('Запись удалена из учёта'), 'restore': gettext_noop('Запись восстановлена'),
             'payment': gettext_noop('Погашение долга'), 'cancel_payment': gettext_noop('Погашение отменено')}[action]
    Activity.objects.create(title=title, detail=str(getattr(record, 'description', None) or getattr(record, 'name', None) or getattr(record, 'vehicle', '')), kind=action)


def changed(record):
    record.revision += 1
    record.modified_at = timezone.now()


def set_record_active(record, kind, active, revision, actor):
    check_revision(record, revision)
    if active and record.archived_at:
        raise ValidationError(gettext('Запись относится к архивному снимку. Восстановление в текущий учёт недоступно.'))
    if not active and getattr(record, 'paid_amount', 0) > 0:
        raise ValidationError(gettext('Сначала отмените погашения этого долга. История оплат должна сохраняться в учёте.'))
    before = snapshot(record)
    record.active = active
    record.deleted_at = None if active else timezone.now()
    changed(record)
    record.save()
    log_change(record, kind, before, 'restore' if active else 'delete', actor)


def change_history(kind, record_id):
    labels = {'date': gettext('Дата'), 'kind': gettext('Тип операции'), 'amount': gettext('Сумма, UZS'),
              'description': gettext('Назначение платежа'), 'category': gettext('Категория'), 'partner': gettext('Контрагент'),
              'direction': gettext('Направление'), 'vehicle': gettext('Номер машины / описание'),
              'gross': gettext('Брутто, кг'), 'tare': gettext('Тара, кг'), 'discount': gettext('Скидка, %'),
              'price': gettext('Цена, UZS/кг'), 'notes': gettext('Примечание'), 'name': gettext('Контрагент'),
              'note': gettext('Основание долга / примечание'), 'balance': gettext('Полная сумма долга, UZS'),
              'paid_amount': gettext('Погашено'), 'due_date': gettext('Срок оплаты'), 'active': gettext('В текущем учёте')}
    actions = {'edit': gettext('Редактирование'), 'create': gettext('Создание'), 'delete': gettext('Удаление'),
               'restore': gettext('Восстановление'), 'payment': gettext('Погашение долга'), 'cancel_payment': gettext('Отмена оплаты')}
    choices = {'income': gettext('Приход'), 'expense': gettext('Расход'), 'in': gettext('Приёмка'), 'out': gettext('Отгрузка')}
    def value(field, data):
        if data is None or data == '':
            return '—'
        if field == 'active':
            return gettext('Да') if data else gettext('Нет')
        return choices.get(data, data) if field in ('kind', 'direction') else data
    changes = list(RecordChange.objects.filter(kind=kind, record_id=record_id)[:50])
    for item in changes:
        item.label = actions.get(item.action, item.action)
        item.deltas = [{'label': label, 'old': value(field, item.before.get(field)), 'new': value(field, item.after.get(field))}
                       for field, label in labels.items() if item.before.get(field) != item.after.get(field)]
    return changes
