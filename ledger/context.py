from django.utils.translation import gettext
from django.db.models import F
from .models import ImportBatch, WorkingWorkbook


def workspace(request):
    if not request.user.is_authenticated:
        return {}
    batch = ImportBatch.objects.filter(format='legacy', status='imported').first()
    return {'current_batch': batch,
            'pending_workbook': WorkingWorkbook.objects.filter(batch=batch, revision__gt=F('applied_revision')).only('pk').first() if batch else None,
            'client_messages': {
                # Match the server's money filter in both interface languages:
                # spaces group thousands and a comma separates decimals.
                'numberLocale': 'ru-RU',
                'dropFile': gettext('Перетащите файл сюда'),
                'fileError': gettext('Выберите .xlsx размером до 10 МБ.'),
                'checking': gettext('Проверяем книгу…'),
                'emptyChart': gettext('Загрузите операции с датами, чтобы увидеть динамику.'),
                'income': gettext('Приход'), 'expense': gettext('Расход'),
                'kg': gettext('кг'),
                'months': [gettext('янв'), gettext('фев'), gettext('мар'), gettext('апр'),
                           gettext('май'), gettext('июн'), gettext('июл'), gettext('авг'),
                           gettext('сен'), gettext('окт'), gettext('ноя'), gettext('дек')],
            }}
