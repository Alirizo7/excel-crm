"""Translate system text at display time; workbook data stays in its original form."""
import re

from django.utils.translation import gettext, gettext_noop


# Django's Uzbek catalogue leaves these numeric validator messages untranslated.
DJANGO_VALIDATOR_MESSAGES = (
    gettext_noop('Ensure this value is less than or equal to %(limit_value)s.'),
    gettext_noop('Ensure this value is greater than or equal to %(limit_value)s.'),
)


# Older imports store complete messages. Keep them readable in either language
# without rewriting the audit trail or reimporting the workbook.
ISSUE_PATTERNS = [
    (re.compile(r'^Ошибка Excel (?P<error>.+)\. Исходная формула сохранена; значение исключено из расчётов\.$'),
     gettext_noop('Ошибка Excel %(error)s. Исходная формула сохранена; значение исключено из расчётов.')),
    (re.compile(r'^В исходный итог включена корректировка (?P<amount>.+) UZS\. Она не является поставкой и не добавляется к стоимости отгрузок\.$'),
     gettext_noop('В исходный итог включена корректировка %(amount)s UZS. Она не является поставкой и не добавляется к стоимости отгрузок.')),
    (re.compile(r'^(?P<count>\d+) денежных операций без даты\. Они входят в общий итог, но не в отчёты за период\.$'),
     gettext_noop('%(count)s денежных операций без даты. Они входят в общий итог, но не в отчёты за период.')),
    (re.compile(r'^Строка (?P<row>\d+): (?P<error>.+)$'),
     gettext_noop('Строка %(row)s: %(error)s')),
]


def localize_system_text(value):
    text = str(value)
    for pattern, template in ISSUE_PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            values = match.groupdict()
            if 'error' in values:
                values['error'] = gettext(values['error'])
            return gettext(template) % values
    return gettext(text)
