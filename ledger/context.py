from django.conf import settings
from django.utils.translation import gettext
from .models import ImportBatch, Operation


def workspace(request):
    return {'current_batch': ImportBatch.objects.filter(format='legacy', status='imported').first(),
            'local_workspace': settings.LOCAL_WORKSPACE,
            'nav_operation_count': Operation.objects.filter(active=True).count(),
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
