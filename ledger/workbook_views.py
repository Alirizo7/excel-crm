import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _, gettext_noop
from django.views.decorators.http import require_POST

from .models import ImportBatch, WorkingWorkbook, WorkbookVersion
from .services.workbooks import create_book, save_book, restore_book, preview_book, apply_book, WorkbookConflict
from .services.workbook_files import formula_errors, write_xlsx


def responsible(request):
    return request.user.is_staff or request.user.has_perm('ledger.edit_workbook_formulas')


def actor(request):
    return request.user.get_username() if request.user.is_authenticated else ''


def index(request):
    return render(request, 'ledger/workbooks.html', {'nav': 'workbooks', 'title': _('Рабочие книги'),
        'batches': ImportBatch.objects.filter(status='imported').select_related('working_book'),
        'archived': WorkingWorkbook.objects.filter(batch__status='superseded').select_related('batch')})


@require_POST
def create(request, batch_id):
    get_object_or_404(ImportBatch, pk=batch_id, status='imported')
    try:
        book = create_book(batch_id, actor(request))
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
        return redirect('workbooks')
    return redirect('workbook_detail', pk=book.pk)


def editor(request, pk, version=None):
    book = get_object_or_404(WorkingWorkbook.objects.select_related('batch'), pk=pk)
    historical = get_object_or_404(WorkbookVersion, workbook=book, revision=version) if version else None
    read_only = bool(historical) or book.batch.status != 'imported'
    return render(request, 'ledger/workbook_editor.html', {'nav': 'workbooks', 'title': _('Рабочая книга'),
        'book': book, 'historical': historical, 'readonly': read_only, 'can_formulas': responsible(request),
        'ui': {k: _(v) for k, v in {
            'sheet': gettext_noop('Лист'), 'notFound': gettext_noop('Ничего не найдено'),
            'loading': gettext_noop('Загружаем листы и формулы…'), 'ready': gettext_noop('Все изменения сохранены'),
            'dirty': gettext_noop('Есть несохранённые изменения'), 'saving': gettext_noop('Проверяем расчёты и сохраняем…'),
            'saved': gettext_noop('Сохранено'), 'failed': gettext_noop('Не удалось сохранить. Правки остаются на экране.'),
            'conflict': gettext_noop('Книга изменена в другой вкладке. Скачайте свои правки перед обновлением.'),
            'locked': gettext_noop('Формула защищена. Включите режим редактирования формул.'),
            'structure': gettext_noop('Изменение структуры доступно ответственному. Колонки и листы сохраняют исходный порядок.'),
            'formula': gettext_noop('Формула'), 'value': gettext_noop('Значение'), 'errors': gettext_noop('Ошибки формул'), 'noErrors': gettext_noop('Ошибок формул нет'),
            'legacyRange': gettext_noop('Ссылка на целый диапазон требует исправления. Соседние ячейки сохранены.'),
            'addRow': gettext_noop('Добавить строку по образцу'), 'rowAdded': gettext_noop('Строка добавлена. Заполните исходные поля.'),
            'selectRow': gettext_noop('Выберите строку данных ниже заголовка.'), 'newFormulaMode': gettext_noop('Режим редактирования формул включён'),
            'draft': gettext_noop('Черновик книги'), 'applied': gettext_noop('Применено к учёту'), 'readOnly': gettext_noop('Просмотр сохранённой версии'),
            'offlineExport': gettext_noop('Скачать несохранённую копию'), 'loadFail': gettext_noop('Не удалось открыть книгу. Обновите страницу.'),
        }.items()}})


def data(request, pk):
    book = get_object_or_404(WorkingWorkbook.objects.select_related('batch'), pk=pk)
    payload = book.data
    if request.GET.get('version'):
        import zlib
        item = get_object_or_404(WorkbookVersion, workbook=book, revision=request.GET['version'])
        payload = json.loads(zlib.decompress(item.payload))
    response = JsonResponse({'data': payload, 'revision': book.revision, 'applied_revision': book.applied_revision,
        'errors': formula_errors(payload), 'readonly': book.batch.status != 'imported' or bool(request.GET.get('version'))})
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
def save(request, pk):
    get_object_or_404(WorkingWorkbook, pk=pk)
    try:
        body = json.loads(request.body)
        revision = int(body['revision'])
        book = save_book(pk, body['data'], revision, actor(request), responsible(request))
        return JsonResponse({'revision': book.revision, 'errors': formula_errors(book.data), 'applied_revision': book.applied_revision})
    except WorkbookConflict as exc:
        return JsonResponse({'error': ' '.join(exc.messages)}, status=409)
    except ValidationError as exc:
        return JsonResponse({'error': ' '.join(exc.messages)}, status=400)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return JsonResponse({'error': _('Некорректные данные книги.')}, status=400)


def history(request, pk):
    book = get_object_or_404(WorkingWorkbook.objects.select_related('batch'), pk=pk)
    from django.core.paginator import Paginator
    return render(request, 'ledger/workbook_history.html', {'nav': 'workbooks', 'title': _('История рабочей книги'),
        'book': book, 'page': Paginator(book.versions.defer('payload'), 25).get_page(request.GET.get('page')),
        'can_restore': book.batch.status == 'imported', 'can_formulas': responsible(request)})


@require_POST
def restore(request, pk, version):
    get_object_or_404(WorkbookVersion, workbook_id=pk, revision=version)
    try:
        restore_book(pk, version, int(request.POST.get('revision', '')), actor(request), responsible(request))
        messages.success(request, _('Версия восстановлена в черновик. Учёт изменится после проверки и применения.'))
    except (ValueError, ValidationError) as exc:
        messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else _('Обновите страницу и повторите действие.'))
    return redirect('workbook_history', pk=pk)


def preview(request, pk):
    book = get_object_or_404(WorkingWorkbook.objects.select_related('batch'), pk=pk)
    try:
        plans, blocked, token, projected, issues = preview_book(book)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
        return redirect('workbook_detail', pk=pk)
    labels = {'operations': _('Операция'), 'deliveries': _('Поставка'), 'balances': _('Долг')}
    actions = {'create': _('Добавление'), 'edit': _('Изменение'), 'delete': _('Удаление'), 'restore': _('Восстановление')}
    fields = {'date': _('Дата'), 'kind': _('Тип операции'), 'amount': _('Сумма, UZS'), 'description': _('Назначение платежа'),
              'category': _('Категория'), 'partner': _('Контрагент'), 'direction': _('Направление'), 'vehicle': _('Номер машины / описание'),
              'gross': _('Брутто, кг'), 'tare': _('Тара, кг'), 'discount': _('Скидка, %'), 'price': _('Цена, UZS/кг'),
              'notes': _('Примечание'), 'name': _('Контрагент'), 'balance': _('Полная сумма долга, UZS'), 'note': _('Примечание'),
              'net': _('Нетто, кг'), 'clean_weight': _('Чистый вес, кг')}
    choices = {'income': _('Приход'), 'expense': _('Расход'), 'in': _('Приёмка'), 'out': _('Отгрузка')}
    for plan in plans:
        plan['label'] = labels[plan['kind']]
        plan['action_label'] = actions[plan['action']]
        plan['deltas'] = [{'label': fields[f],
                           'old': plan['before'].get(f), 'new': plan['after'].get(f)} for f in plan['fields']]
        if plan['kind'] == 'deliveries' and plan['action'] != 'delete':
            for field in ('net', 'clean_weight', 'amount'):
                old, new = plan['before'].get(field), str(getattr(plan['candidate'], field))
                if old != new:
                    plan['deltas'].append({'label': fields[field], 'old': old, 'new': new})
        for delta in plan['deltas']:
            for side in ('old', 'new'):
                delta[side] = choices.get(delta[side], delta[side])
        plan['detail_kind'] = 'partners' if plan['kind'] == 'balances' else plan['kind']
    return render(request, 'ledger/workbook_preview.html', {'nav': 'workbooks', 'title': _('Применение книги к учёту'),
        'book': book, 'plans': plans, 'blocked': blocked, 'token': token,
        'can_apply': not blocked and not any(p['errors'] for p in plans),
        'errors': formula_errors(book.data)})


@require_POST
def apply(request, pk):
    get_object_or_404(WorkingWorkbook, pk=pk)
    try:
        count = apply_book(pk, int(request.POST.get('revision', '')), request.POST.get('token', ''), actor(request))
        messages.success(request, _('Изменения рабочей книги применены к учёту.') + f' {count}')
    except (ValueError, ValidationError) as exc:
        messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else _('Обновите страницу и повторите действие.'))
        return redirect('workbook_preview', pk=pk)
    return redirect('workbook_detail', pk=pk)


def download(request, pk):
    book = get_object_or_404(WorkingWorkbook.objects.select_related('batch'), pk=pk)
    data = book.data
    download_revision = book.revision
    if request.GET.get('version'):
        import zlib
        version = get_object_or_404(WorkbookVersion, workbook=book, revision=request.GET['version'])
        data = json.loads(zlib.decompress(version.payload))
        download_revision = version.revision
    response = HttpResponse(write_xlsx(data), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="metalflow-workbook-{pk}-v{download_revision}.xlsx"'
    response['Cache-Control'] = 'no-store'
    return response
