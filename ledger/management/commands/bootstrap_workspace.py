import hashlib
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ledger.models import (
    Activity,
    Counterparty,
    DebtPayment,
    Delivery,
    ImportBatch,
    Operation,
    PartnerBalance,
    RecordChange,
    SourceSheet,
    WorkingWorkbook,
    WorkbookVersion,
)


SEED_DIR = Path(settings.BASE_DIR) / 'starter_data'
FIXTURE = SEED_DIR / 'workspace.json.gz'
WORKBOOK = SEED_DIR / '01.09.2026.xlsx'
WORKBOOK_SHA256 = 'fd3183a8287e8bcd6e698cffd40f689d949d1725a3fcdf9977f5068154897df5'
WORKBOOK_MEDIA_NAME = 'imports/2026/09/ca2a18d72cf242788e022622d74cdf6f.xlsx'


class Command(BaseCommand):
    help = 'Установить готовую стартовую базу и загруженный Excel в пустой проект'

    def handle(self, *args, **options):
        if ImportBatch.objects.exists():
            self.stdout.write('Стартовые данные уже установлены; существующая база сохранена.')
            return

        business_models = (
            Operation, Delivery, PartnerBalance, DebtPayment, RecordChange,
            Activity, WorkingWorkbook, WorkbookVersion, SourceSheet, Counterparty,
        )
        if any(model.objects.exists() for model in business_models):
            raise CommandError('База уже содержит данные. Автоматическая установка отменена, чтобы их не перезаписать.')
        if not FIXTURE.is_file() or not WORKBOOK.is_file():
            raise CommandError('В проекте отсутствует полный стартовый набор данных.')
        if hashlib.sha256(WORKBOOK.read_bytes()).hexdigest() != WORKBOOK_SHA256:
            raise CommandError('Стартовый Excel повреждён: контрольная сумма не совпадает.')

        destination = Path(settings.MEDIA_ROOT) / WORKBOOK_MEDIA_NAME
        destination.parent.mkdir(parents=True, exist_ok=True)
        created_file = not destination.exists()
        if created_file:
            shutil.copyfile(WORKBOOK, destination)
        elif hashlib.sha256(destination.read_bytes()).hexdigest() != WORKBOOK_SHA256:
            raise CommandError(f'Файл {destination} уже существует и отличается от стартового Excel.')

        try:
            with transaction.atomic():
                call_command('loaddata', str(FIXTURE), verbosity=0)
                batch = ImportBatch.objects.select_related('working_book').get(sha256=WORKBOOK_SHA256)
                if batch.file.name != WORKBOOK_MEDIA_NAME or batch.status != 'imported':
                    raise CommandError('Стартовый снимок не прошёл внутреннюю проверку.')
        except Exception:
            if created_file:
                destination.unlink(missing_ok=True)
            raise

        self.stdout.write(self.style.SUCCESS(
            'Готовая база установлена: пользователь admin, Excel 01.09.2026.xlsx и рабочая таблица.'
        ))
