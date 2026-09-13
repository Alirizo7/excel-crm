from django.utils.translation import gettext_noop
from decimal import Decimal, InvalidOperation
from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from pathlib import Path
from django.utils.translation import gettext
from ledger.i18n import localize_system_text
register = template.Library()


@register.simple_tag
def versioned_static(name):
    """Refresh rebuilt editor assets even when a browser retains its old bundle."""
    url = static(name)
    source = finders.find(name) if settings.DEBUG else Path(settings.STATIC_ROOT) / name
    try:
        return f'{url}?v={Path(source).stat().st_mtime_ns}' if source else url
    except OSError:
        return url


@register.filter
def ui(value):
    return localize_system_text(value)


@register.filter
def money(value, places=0):
    if value is None or value == '':
        return '—'
    try:
        return f'{Decimal(str(value)):,.{int(places)}f}'.replace(',', '\u00a0').replace('.', ',')
    except InvalidOperation:
        return value


@register.filter
def compact(value):
    value = Decimal(value or 0)
    for size, suffix in [(Decimal('1e9'), gettext_noop('млрд')), (Decimal('1e6'), gettext_noop('млн')), (Decimal('1e3'), gettext_noop('тыс.'))]:
        if abs(value) >= size:
            return money(value/size, 2) + ' ' + gettext(suffix)
    return money(value)


@register.filter
def tonnes(value):
    return money(Decimal(value or 0)/1000, 2)


@register.filter
def absolute(value):
    return abs(value or 0)


@register.simple_tag(takes_context=True)
def query_page(context, page):
    params = context['request'].GET.copy()
    params['page'] = page
    return '?' + params.urlencode()
