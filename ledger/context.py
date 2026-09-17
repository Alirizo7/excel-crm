from django.utils.translation import gettext
from .models import ImportBatch


def workspace(request):
    if not request.user.is_authenticated:
        return {}
    current = getattr(request, 'workspace', None)
    batch = ImportBatch.objects.filter(workspace=current, format='legacy', status='imported').first() if current else None
    return {'current_workspace': current, 'current_batch': batch,
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
