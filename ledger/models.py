from django.utils.translation import gettext_lazy as _
import uuid
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


class WorkspaceState(models.Model):
    """One database row serializes writes, including SQLite imports/payments."""
    revision = models.PositiveBigIntegerField(default=0)


class Counterparty(models.Model):
    name = models.CharField(_('Контрагент'), max_length=250)
    key = models.CharField(max_length=500, unique=True)

    class Meta:
        ordering = ['name', 'pk']

    def __str__(self):
        return self.name


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PREVIEW = 'preview', _('На проверке')
        IMPORTED = 'imported', _('Импортирован')
        SUPERSEDED = 'superseded', _('Архив')
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='imports/%Y/%m/')
    sha256 = models.CharField(max_length=64, unique=True)
    format = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREVIEW)
    report_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True)
    payload = models.JSONField(default=dict)
    issues = models.JSONField(default=list)
    summary = models.JSONField(default=dict)

    class Meta:
        ordering = ['-created_at']


class SourceSheet(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='sheets')
    name = models.CharField(max_length=100)
    position = models.PositiveIntegerField()
    rows = models.JSONField(default=list)
    columns = models.PositiveIntegerField(default=1)
    formula_count = models.PositiveIntegerField(default=0)
    role = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ['position']


class ActiveRecord(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    batch = models.ForeignKey(ImportBatch, null=True, blank=True, on_delete=models.PROTECT)
    active = models.BooleanField(default=True, db_index=True)
    source_sheet = models.CharField(max_length=100, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revision = models.PositiveIntegerField(default=0)
    modified_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class Operation(ActiveRecord):
    class Kind(models.TextChoices):
        INCOME = 'income', _('Приход')
        EXPENSE = 'expense', _('Расход')
    date = models.DateField(_('Дата'), null=True, blank=True, db_index=True)
    kind = models.CharField(_('Тип операции'), max_length=10, choices=Kind.choices)
    amount = models.DecimalField(_('Сумма, UZS'), max_digits=20, decimal_places=2,
                                help_text=_('Отрицательная сумма означает сторно в выбранном типе операции.'))
    description = models.CharField(_('Назначение платежа'), max_length=500)
    category = models.CharField(_('Категория'), max_length=80, default='Прочее')
    partner = models.CharField(_('Контрагент'), max_length=150, blank=True)

    class Meta:
        ordering = ['-date', '-id']
        constraints = [models.CheckConstraint(condition=~models.Q(amount=0), name='nonzero_operation_amount')]


class Delivery(ActiveRecord):
    class Direction(models.TextChoices):
        OUT = 'out', _('Отгрузка')
        IN = 'in', _('Приёмка')
    date = models.DateField(_('Дата'), null=True, blank=True, db_index=True)
    direction = models.CharField(_('Направление'), max_length=5, choices=Direction.choices, default='out')
    partner = models.CharField(_('Контрагент'), max_length=150)
    vehicle = models.CharField(_('Номер машины / описание'), max_length=150)
    gross = models.DecimalField(_('Брутто, кг'), max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    tare = models.DecimalField(_('Тара, кг'), max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    discount = models.DecimalField(_('Скидка, %'), max_digits=6, decimal_places=3, default=0,
                                   validators=[MinValueValidator(0), MaxValueValidator(100)])
    price = models.DecimalField(_('Цена, UZS/кг'), max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    notes = models.CharField(_('Примечание'), max_length=500, blank=True)
    # Values are computed once by the domain service and retained for indexed aggregation.
    net = models.DecimalField(max_digits=14, decimal_places=3)
    clean_weight = models.DecimalField(max_digits=14, decimal_places=3)
    amount = models.DecimalField(max_digits=20, decimal_places=2)

    def save(self, *args, **kwargs):
        self.net, self.clean_weight, self.amount = self.calculate(self.gross, self.tare, self.discount, self.price)
        super().save(*args, **kwargs)

    @staticmethod
    def calculate(gross, tare, discount, price):
        net = Decimal(gross) - Decimal(tare)
        clean = net * (1 - Decimal(discount) / 100)
        return net.quantize(Decimal('.001')), clean.quantize(Decimal('.001')), (clean * Decimal(price)).quantize(Decimal('.01'))

    class Meta:
        ordering = ['-date', '-id']
        constraints = [models.CheckConstraint(condition=models.Q(gross__gte=models.F('tare')), name='gross_above_tare'),
                       models.CheckConstraint(condition=models.Q(discount__gte=0, discount__lte=100), name='discount_range'),
                       models.CheckConstraint(condition=models.Q(tare__gte=0, price__gte=0), name='positive_delivery_inputs')]


class PartnerBalance(ActiveRecord):
    name = models.CharField(max_length=250)
    receivable_column = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    payable_column = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    note = models.CharField(max_length=500, blank=True)
    counterparty = models.ForeignKey(Counterparty, null=True, on_delete=models.PROTECT, related_name='debts')
    paid_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    due_date = models.DateField(_('Срок оплаты'), null=True, blank=True)

    @property
    def outstanding(self):
        return abs(self.balance) - self.paid_amount

    @property
    def remaining(self):
        return self.outstanding if self.balance >= 0 else -self.outstanding

    @property
    def overdue(self):
        return self.active and self.outstanding > 0 and self.due_date is not None and self.due_date < timezone.localdate()

    class Meta:
        ordering = ['name']
        constraints = [models.CheckConstraint(condition=models.Q(paid_amount__gte=0), name='paid_amount_nonnegative'),
                       models.CheckConstraint(condition=models.Q(paid_amount__lte=models.functions.Abs('balance')), name='paid_within_debt')]


class DebtPayment(models.Model):
    debt = models.ForeignKey(PartnerBalance, on_delete=models.PROTECT, related_name='payments')
    request_key = models.UUIDField(unique=True)
    date = models.DateField(_('Дата оплаты'))
    amount = models.DecimalField(_('Сумма оплаты, UZS'), max_digits=20, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    note = models.CharField(_('Примечание'), max_length=500, blank=True)
    actor = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=500, blank=True)
    cancelled_by = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ['-date', '-created_at', '-pk']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='debt_payment_positive')]


class RecordChange(models.Model):
    kind = models.CharField(max_length=20)
    record_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=20)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    actor = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['kind', 'record_id'])]


class Activity(models.Model):
    title = models.CharField(max_length=255)
    detail = models.CharField(max_length=500, blank=True)
    kind = models.CharField(max_length=30, default='edit')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
