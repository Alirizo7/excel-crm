from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db.models import Q
from ledger.models import Workspace
from ledger.services.importing import stage_import, commit_import


class Command(BaseCommand):
    help = 'Проверить и импортировать рабочую книгу Excel'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--preview', action='store_true')
        parser.add_argument('--debt-policy', choices=['keep', 'replace'])
        parser.add_argument('--replace-local-changes', action='store_true')
        parser.add_argument('--workspace', help='ID или UUID компании (обязателен, если компаний несколько)')

    def handle(self, *args, **options):
        path = Path(options['file'])
        try:
            workspaces = Workspace.objects.all()
            if options['workspace']:
                value = options['workspace']
                lookup = Q(key=value)
                if value.isdigit():
                    lookup |= Q(pk=int(value))
                workspace = workspaces.filter(lookup).first()
                if workspace is None:
                    raise CommandError('Компания не найдена.')
            elif workspaces.count() == 1:
                workspace = workspaces.get()
            else:
                raise CommandError('Укажите --workspace, чтобы данные не попали в другую компанию.')
            batch, created = stage_import(path.read_bytes(), path.name, workspace=workspace)
            self.stdout.write(str(batch.summary))
            if not options['preview'] and batch.status == 'preview':
                commit_import(batch.pk, debt_policy=options['debt_policy'], replace_local_changes=options['replace_local_changes'], workspace=workspace)
                batch.refresh_from_db()
            self.stdout.write(self.style.SUCCESS(f'Файл #{batch.pk}: {batch.get_status_display()}. Проверка: /imports/{batch.pk}/'))
        except (ValidationError, OSError) as exc:
            raise CommandError(str(exc)) from exc
