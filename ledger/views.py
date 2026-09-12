from django.utils.translation import gettext_noop
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.db.models.functions import TruncMonth
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils.translation import gettext

from .forms import DateFilters, DeliveryForm, ImportForm, OperationForm, RevisionForm
from .models import Activity, Delivery, ImportBatch, Operation, PartnerBalance, SourceSheet, DebtPayment
from .i18n import localize_system_text
from .services.exporting import make_export
from .services.importing import MAX_BYTES, stage_import, commit_import, import_impact
from .services.changes import workspace_transaction, snapshot, check_revision, changed, log_change, set_record_active, change_history
from .services.debts import debt_rows, debt_stats
from .debt_views import actor


def filtered(request, model, include_deleted=False):
    records = model.objects.filter(active=True)
    if include_deleted and request.GET.get('status') == 'deleted':
        records = model.objects.filter(deleted_at__isnull=False, archived_at=None)
    filters = DateFilters(request.GET)
    valid = filters.is_valid()
    if valid:
        if filters.cleaned_data.get('start'):
            records = records.filter(date__gte=filters.cleaned_data['start'])
        if filters.cleaned_data.get('end'):
            records = records.filter(date__lte=filters.cleaned_data['end'])
    else:
        records = records.none()
    q = request.GET.get('q', '').strip()
    if q:
        match = Q(partner__icontains=q)
        for field in (['description', 'category'] if model == Operation else ['vehicle', 'notes']):
            match |= Q(**{f'{field}__icontains': q})
        records = records.filter(match)
    if model == Operation:
        if request.GET.get('kind') in ['income', 'expense']:
            records = records.filter(kind=request.GET['kind'])
        if request.GET.get('category'):
            records = records.filter(category=request.GET['category'])
    else:
        if request.GET.get('direction') in ['in', 'out']:
            records = records.filter(direction=request.GET['direction'])
    return records, filters


def totals(operations):
    values = operations.aggregate(income=Sum('amount', filter=Q(kind='income')), expense=Sum('amount', filter=Q(kind='expense')))
    values = {k: v or Decimal(0) for k,v in values.items()}
    values['balance'] = values['income']-values['expense']
    return values


def dashboard(request):
    operations, filters = filtered(request, Operation)
    deliveries, _ = filtered(request, Delivery)
    monthly = list(operations.exclude(date=None).annotate(month=TruncMonth('date')).values('month').annotate(
        income=Sum('amount', filter=Q(kind='income')), expense=Sum('amount', filter=Q(kind='expense'))).order_by('month'))[-12:]
    chart = [{'label': x['month'].strftime('%m.%Y'), 'income': float(x['income'] or 0), 'expense': float(x['expense'] or 0)} for x in monthly]
    stats = totals(operations)
    return render(request, 'ledger/dashboard.html', {'nav': 'dashboard', 'title': gettext_noop('Итоги'), 'stats': stats,
        'filters': filters,
        'shipment_weight': deliveries.filter(direction='out').aggregate(v=Sum('clean_weight'))['v'] or 0,
        'chart_data': chart,
        'debt_stats': debt_stats(debt_rows().filter(active=True)),
        'undated': operations.filter(date=None).count()})


def operations(request):
    records, filters = filtered(request, Operation, include_deleted=True)
    return render(request, 'ledger/operations.html', {'nav': 'operations', 'title': gettext_noop('Денежные операции'),
        'page': Paginator(records, 25).get_page(request.GET.get('page')), 'stats': totals(records), 'filters': filters,
        'categories': Operation.objects.filter(active=True).values_list('category', flat=True).distinct().order_by('category')})


def deliveries(request):
    records, filters = filtered(request, Delivery, include_deleted=True)
    return render(request, 'ledger/deliveries.html', {'nav': 'deliveries', 'title': gettext_noop('Поставки металла'),
        'page': Paginator(records, 25).get_page(request.GET.get('page')), 'filters': filters,
        'out_weight': records.filter(direction='out').aggregate(v=Sum('clean_weight'))['v'] or 0,
        'in_weight': records.filter(direction='in').aggregate(v=Sum('clean_weight'))['v'] or 0,
        'total_amount': records.aggregate(v=Sum('amount'))['v'] or 0})




def record_form(request, kind, pk=None):
    if kind not in ('operations', 'deliveries'):
        raise Http404
    model, form_cls = (Operation, OperationForm) if kind == 'operations' else (Delivery, DeliveryForm)
    obj = get_object_or_404(model, pk=pk, active=True) if pk else None
    form = form_cls(instance=obj, initial={} if pk else {'date': date.today()})
    if request.method == 'POST':
        with workspace_transaction():
            obj = get_object_or_404(model, pk=pk, active=True) if pk else model()
            before = snapshot(obj) if pk else {}
            form = form_cls(request.POST, instance=obj)
            if form.is_valid():
                try:
                    check_revision(obj, form.cleaned_data.get('revision') or 0)
                    item = form.save(commit=False)
                    changed(item)
                    item.save()
                    log_change(item, kind, before, 'edit' if pk else 'create', actor(request))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, gettext_noop('Изменения сохранены. Итоги обновлены.'))
                    return redirect('record_detail', kind=kind, pk=item.pk)
    return render(request, 'ledger/record_form.html', {'nav': kind, 'title': (gettext_noop('Редактирование') if pk else gettext_noop('Новая операция') if kind=='operations' else gettext_noop('Новая поставка')),
        'form': form, 'kind': kind, 'item': obj})


def record_detail(request, kind, pk):
    if kind not in ('operations', 'deliveries'):
        raise Http404
    model = Operation if kind == 'operations' else Delivery
    obj = get_object_or_404(model, pk=pk)
    fields = [(f.verbose_name, f.value_from_object(obj)) for f in model._meta.fields if f.name in
              (['date', 'kind', 'amount', 'description', 'category', 'partner'] if kind=='operations' else
               ['date', 'direction', 'partner', 'vehicle', 'gross', 'tare', 'discount', 'price', 'notes'])]
    source = SourceSheet.objects.filter(batch=obj.batch, name=obj.source_sheet).first() if obj.batch_id else None
    return render(request, 'ledger/record_detail.html', {'nav':kind, 'title':gettext_noop('Карточка операции') if kind=='operations' else gettext_noop('Карточка поставки'),
        'item':obj, 'kind':kind, 'fields':fields, 'source':source, 'changes':change_history(kind, pk),
        'can_restore': bool(obj.deleted_at) and not obj.archived_at})


@require_POST
def record_delete(request, kind, pk, restore=False):
    if kind not in ('operations', 'deliveries'):
        raise Http404
    model = Operation if kind=='operations' else Delivery
    form = RevisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, gettext('Обновите страницу и повторите действие.'))
        return redirect('record_detail', kind=kind, pk=pk)
    with workspace_transaction():
        obj = get_object_or_404(model.objects.select_related('batch'), pk=pk, active=not restore)
        try:
            set_record_active(obj, kind, restore, form.cleaned_data['revision'], actor(request))
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        else:
            messages.success(request, gettext('Запись восстановлена.') if restore else gettext('Запись удалена из текущего учёта.'))
    return redirect('record_detail', kind=kind, pk=pk)


def imports(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        upload = form.cleaned_data['file']
        if upload.size > MAX_BYTES:
            form.add_error('file', gettext('Максимальный размер файла — 10 МБ.'))
        else:
            try:
                batch, created = stage_import(upload.read(), upload.name, form.cleaned_data['report_date'])
                if not created:
                    messages.info(request, gettext_noop('Этот файл уже загружен. Открыта существующая проверка; дубликат не создан.'))
                return redirect('import_detail', pk=batch.pk)
            except ValidationError as exc:
                form.add_error('file', ValidationError([localize_system_text(message) for message in exc.messages]))
    return render(request, 'ledger/imports.html', {'nav':'workbooks', 'title':gettext_noop('Загрузить Excel'), 'form':form,
                                                 'batches':ImportBatch.objects.all()[:15]})


def import_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    issues = batch.issues
    return render(request, 'ledger/import_detail.html', {'nav':'workbooks', 'title':gettext_noop('Проверка файла'), 'batch':batch,
        'issues': Paginator(issues, 25).get_page(request.GET.get('page')),
        'preview_operations': batch.payload.get('operations', [])[:5],
        'impact': import_impact() if batch.format == 'legacy' else {},
        'active_legacy':ImportBatch.objects.filter(format='legacy', status='imported').exclude(pk=pk).first()})


@require_POST
def import_confirm(request, pk):
    get_object_or_404(ImportBatch, pk=pk)
    try:
        commit_import(pk, debt_policy=request.POST.get('debt_policy') or None,
                      replace_local_changes=request.POST.get('replace_local_changes') == 'on')
        messages.success(request, gettext_noop('Импорт завершён. Данные доступны в учёте и отчётах.'))
    except ValidationError as exc:
        messages.error(request, ' '.join(localize_system_text(message) for message in exc.messages))
        return redirect('import_detail', pk=pk)
    from .services.workbooks import create_book
    batch = ImportBatch.objects.get(pk=pk)
    if batch.format == 'legacy':
        try:
            book = create_book(pk, actor(request))
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
            return redirect('workbooks')
        return redirect('workbook_detail', pk=book.pk)
    return redirect('operations' if batch.format == 'operations' else 'deliveries')


def sheets(request):
    return redirect(reverse('imports') + '#file-history')


def sheet_detail(request, pk):
    sheet = get_object_or_404(SourceSheet.objects.select_related('batch'), pk=pk)
    rows = sheet.rows
    q = request.GET.get('q', '').lower().strip()
    if q:
        rows = [row for row in rows if any(q in str(c.get('value', '')).lower() or q in str(c.get('formula', '')).lower() for c in row['cells'])]
    page = Paginator(rows, 40).get_page(request.GET.get('page'))
    if request.GET.get('row', '').isdigit():
        row = int(request.GET['row'])
        for i, entry in enumerate(rows):
            if entry['number'] >= row:
                page = Paginator(rows, 40).get_page(i//40+1)
                break
    from openpyxl.utils import get_column_letter
    return render(request, 'ledger/sheet_detail.html', {'nav':'sheets', 'title':sheet.name, 'sheet':sheet, 'page':page,
        'letters':[get_column_letter(i) for i in range(1, sheet.columns+1)]})


def exports(request):
    return redirect(reverse('dashboard') + ('?' + request.GET.urlencode() if request.GET else '') + '#reports')


def export_download(request, kind):
    if kind not in ('operations','deliveries','partners','report'):
        raise Http404
    ops, filters = filtered(request, Operation)
    dels, _ = filtered(request, Delivery)
    if not filters.is_valid():
        return HttpResponse(gettext('Некорректный период выгрузки.'), status=400)
    template = request.GET.get('template') == '1'
    if template and kind not in ('operations','deliveries'):
        raise Http404
    batch = ImportBatch.objects.filter(format='legacy', status='imported').first()
    payments = DebtPayment.objects.select_related('debt').all()
    if filters.cleaned_data.get('start'):
        payments = payments.filter(date__gte=filters.cleaned_data['start'])
    if filters.cleaned_data.get('end'):
        payments = payments.filter(date__lte=filters.cleaned_data['end'])
    data = make_export(kind, ops, dels, PartnerBalance.objects.filter(active=True), batch.issues if batch else [], template, payments=payments)
    response = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="metalflow-{kind}-{"template" if template else date.today().isoformat()}.xlsx"'
    response['Cache-Control'] = 'no-store'
    Activity.objects.create(title=gettext_noop('Шаблон скачан') if template else gettext_noop('Отчёт экспортирован'), detail={'operations':gettext_noop('Денежные операции'),'deliveries':gettext_noop('Поставки'),'partners':gettext_noop('Взаиморасчёты'),'report':gettext_noop('Полный отчёт')}[kind], kind='export')
    return response


def source_download(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    if not batch.file or not Path(batch.file.path).exists():
        raise Http404('Исходный файл недоступен')
    return FileResponse(batch.file.open('rb'), as_attachment=True, filename=batch.filename)


def help_page(request):
    return redirect('workbooks')
