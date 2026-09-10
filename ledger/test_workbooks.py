import copy
import hashlib
import json
import math
import os
import uuid
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from .models import WorkingWorkbook, Operation, Delivery, PartnerBalance, DebtPayment, RecordChange
from .tests import legacy_bytes
from .services.changes import snapshot, changed, log_change
from .services.debts import record_payment
from .services.importing import stage_import, commit_import
from .services.workbook_files import read_xlsx, validate_snapshot, calculate, write_xlsx, formula_errors, cells
from .services.workbooks import create_book, save_book, restore_book, preview_book, apply_book, WorkbookConflict


class WorkbookTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.get(username='admin'))

    @classmethod
    def setUpClass(cls):
        cls.media = TemporaryDirectory()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media.name)
        cls.media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.media_override.disable(); cls.media.cleanup()

    @classmethod
    def setUpTestData(cls):
        cls.batch, _ = stage_import(legacy_bytes(), '01.09.2026.xlsx')
        commit_import(cls.batch.pk)
        cls.book = create_book(cls.batch.pk, 'tester')

    def edited(self, sheet, r, c, value, formula=False, allowed=True):
        self.book.refresh_from_db()
        data = copy.deepcopy(self.book.data)
        ws = next(s for s in data['sheets'].values() if s['name'] == sheet)
        cell = ws['cellData'].setdefault(str(r-1), {}).setdefault(str(c-1), {})
        cell.pop('f', None); cell.pop('v', None)
        if value is not None: cell['f' if formula else 'v'] = value
        self.book = save_book(self.book.pk, data, self.book.revision, 'tester', allowed)
        return self.book

    def apply(self):
        self.book.refresh_from_db()
        plans, blocked, token, *_ = preview_book(self.book)
        self.assertEqual(blocked, [])
        self.assertFalse([p['errors'] for p in plans if p['errors']])
        return apply_book(self.book.pk, self.book.revision, token, 'tester')

    def test_create_is_idempotent_and_preserves_source_and_records(self):
        initial = Path(self.batch.file.path).read_bytes()
        self.assertEqual(create_book(self.batch.pk,'other').pk, self.book.pk)
        self.assertEqual(WorkingWorkbook.objects.count(),1)
        self.assertEqual(Operation.objects.count(),4)
        self.assertEqual(formula_errors(self.book.data),[])
        self.assertEqual(self.apply(),0)
        self.assertEqual(Path(self.batch.file.path).read_bytes(),initial)

    def test_live_formula_chain_save_export_restore_and_stale_write(self):
        initial = self.book.revision
        self.edited('тура ака',4,6,30000,allowed=False)
        ws=next(s for s in self.book.data['sheets'].values() if s['name']=='тура ака')
        self.assertEqual(ws['cellData']['3']['7']['v'],16110)
        self.assertEqual(ws['cellData']['3']['11']['v'],59010930)
        self.assertEqual(Delivery.objects.get().gross,26610)
        payload=write_xlsx(self.book.data)
        cached=load_workbook(BytesIO(payload),data_only=True)
        formulas=load_workbook(BytesIO(payload),data_only=False)
        self.assertEqual(cached['тура ака']['L4'].value,59010930)
        self.assertEqual(formulas['тура ака']['L4'].value,'=J4*K4')
        with self.assertRaises(WorkbookConflict):save_book(self.book.pk,self.book.data,initial,'tester',True)
        self.assertEqual(self.apply(),1)
        self.assertEqual(Delivery.objects.get().amount,Decimal('59010930'))
        self.book=restore_book(self.book.pk,initial,self.book.revision,'tester',True)
        self.assertEqual(self.apply(),1)
        self.assertEqual(Delivery.objects.get().gross,26610)
        self.assertEqual(self.book.versions.count(),3)

    def test_formula_permissions_and_literal_text(self):
        with self.assertRaises(ValidationError):self.edited('тура ака',4,8,'=1+1',True,False)
        self.edited('Приход-Расход',4,3,'=Это текст',False,False)
        ws=next(s for s in self.book.data['sheets'].values() if s['name']=='Приход-Расход')
        self.assertNotIn('f',ws['cellData']['3']['2'])
        out=load_workbook(BytesIO(write_xlsx(self.book.data)),data_only=False)
        self.assertEqual(out['Приход-Расход']['C4'].data_type,'s')

    def test_apply_preserves_payments_and_rejects_changed_preview(self):
        debt=PartnerBalance.objects.get(name='Партнёр А')
        record_payment(debt.pk,amount=Decimal('100'),date=date(2026,9,1),note='',request_key=uuid.uuid4(),revision=debt.revision,actor='tester')
        self.edited('Кунлик',5,4,1500)
        plans,blocked,token,*_=preview_book(self.book)
        self.assertEqual(blocked,[])
        debt.refresh_from_db()
        record_payment(debt.pk,amount=Decimal('50'),date=date(2026,9,1),note='',request_key=uuid.uuid4(),revision=debt.revision,actor='tester')
        with self.assertRaises(WorkbookConflict):apply_book(self.book.pk,self.book.revision,token,'tester')
        self.assertEqual(self.apply(),1)
        debt.refresh_from_db();self.assertEqual(debt.balance,1250);self.assertEqual(debt.paid_amount,150)
        self.assertEqual(debt.outstanding,1100);self.assertEqual(DebtPayment.objects.count(),2)
        self.assertEqual(self.apply(),0)
        self.edited('Кунлик',5,4,300)
        plans,*_=preview_book(self.book);self.assertTrue(any(p['errors'] for p in plans))

    def test_unrelated_crm_edit_preserved_and_same_field_conflict_blocked(self):
        record=Operation.objects.get(kind='income',source_row=4)
        record.description='Правка CRM';record.save()
        self.edited('Приход-Расход',4,5,900)
        self.assertEqual(self.apply(),1)
        record.refresh_from_db();self.assertEqual(record.description,'Правка CRM');self.assertEqual(record.amount,900)
        self.edited('Приход-Расход',4,5,1000)
        record.amount=950;record.save()
        plans,*_=preview_book(self.book);self.assertTrue(plans[0]['errors'])

    def test_invalid_number_does_not_silently_delete_operation(self):
        self.edited('Приход-Расход',4,5,'не число')
        plans,blocked,*_=preview_book(self.book)
        self.assertTrue(blocked)
        self.assertEqual(Operation.objects.filter(active=True).count(),4)

    def test_soft_delete_and_restore_keep_uid_and_history(self):
        record=Operation.objects.get(kind='income',source_row=4);uid=record.uid
        self.edited('Приход-Расход',4,5,None)
        self.assertEqual(self.apply(),1)
        record.refresh_from_db();self.assertFalse(record.active)
        self.book=restore_book(self.book.pk,1,self.book.revision,'tester',True)
        self.assertEqual(self.apply(),1)
        record.refresh_from_db();self.assertTrue(record.active);self.assertEqual(record.uid,uid)
        self.assertEqual(Operation.objects.count(),4)
        self.assertTrue(RecordChange.objects.filter(record_id=record.pk,action='restore').exists())

    def test_new_formula_errors_and_inconsistent_delivery_totals_block_apply(self):
        self.edited('Приход-Расход',4,5,'=1/0',True)
        plans,blocked,*_=preview_book(self.book);self.assertTrue(blocked)
        self.book=restore_book(self.book.pk,1,self.book.revision,'tester',True)
        self.edited('тура ака',4,12,'=J4*K4+100',True)
        self.assertContains(self.client.get(reverse('workbook_history',args=[self.book.pk])),'=J4*K4+100')
        plans,blocked,*_=preview_book(self.book)
        self.assertTrue(any(p['errors'] for p in plans))

    def test_invalid_structures_external_formulas_and_resources(self):
        for change in [lambda d: d['sheets']['sheet-0'].update(columnCount=100000),
                       lambda d: d['sheets']['sheet-0']['rowData']['3'].update(h='bad'),
                       lambda d: d['sheets']['sheet-0'].update(mergeData=[{'startRow':-1}]),
                       lambda d: d['styles'].update(evil={'fs':float('inf')}),
                       lambda d: d['sheets']['sheet-0']['cellData']['3']['1'].update(f='=WEBSERVICE("https://example.com")'),
                       lambda d: d['sheets']['sheet-0']['cellData']['3']['1'].update(f="='[other.xlsx]Sheet1'!A1")]:
            with self.subTest(change=change):
                data=copy.deepcopy(self.book.data);change(data)
                with self.assertRaises(ValidationError):validate_snapshot(data,self.book.data)
        data=copy.deepcopy(self.book.data);data['resources']=[{'name':'external','data':'x'}]
        self.assertNotIn('resources',validate_snapshot(data,self.book.data))

    def test_pages_post_validation_and_archive(self):
        for url in ['workbooks','workbook_detail','workbook_history','workbook_preview','workbook_data','workbook_download']:
            response=self.client.get(reverse(url,args=[] if url=='workbooks' else [self.book.pk]))
            self.assertEqual(response.status_code,200,url)
        response=self.client.post(reverse('workbook_save',args=[self.book.pk]),data='{}',content_type='application/json')
        self.assertEqual(response.status_code,400)
        new,_=stage_import(legacy_bytes(income=999),'02.09.2026.xlsx');commit_import(new.pk)
        with self.assertRaises(ValidationError):self.edited('Приход-Расход',4,5,777)
        self.assertContains(self.client.get(reverse('workbook_detail',args=[self.book.pk])),'data-readonly="true"')

    def test_anonymous_cannot_read_financial_workbook(self):
        self.client.logout()
        response=self.client.get(reverse('workbook_data',args=[self.book.pk]))
        self.assertEqual(response.status_code,302)
        user=get_user_model().objects.create_user('operator',password='test-only-password')
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse('workbook_detail',args=[self.book.pk])),'data-formulas="false"')

    def test_default_admin_can_edit_formulas(self):
        self.assertContains(self.client.get(reverse('workbook_detail', args=[self.book.pk])), 'data-formulas="true"')


@skipUnless(os.getenv('WORKBOOK_PATH'), 'Set WORKBOOK_PATH to check the original customer workbook')
class OriginalWorkbookParityTests(TestCase):
    def test_all_formulas_preserved_except_explicit_legacy_range_error(self):
        original=Path(os.environ['WORKBOOK_PATH']).read_bytes();checksum=hashlib.sha256(original).hexdigest()
        data=calculate(validate_snapshot(read_xlsx(original,'original.xlsx')))
        cached=load_workbook(BytesIO(original),data_only=True)
        count=0
        for sid,r,c,cell in cells(data):
            if not cell.get('f'):continue
            count+=1;name=data['sheets'][sid]['name'];expected=cached[name].cell(r+1,c+1).value
            if name=='тура ака' and (r,c)==(877,0):self.assertEqual(cell['v'],'#N/A');continue
            if isinstance(expected, datetime):
                from openpyxl.utils.datetime import to_excel
                expected=to_excel(expected)
            if isinstance(expected,(int,float)):
                self.assertTrue(math.isclose(cell.get('v',0),expected,rel_tol=1e-12,abs_tol=1e-5),(name,r+1,c+1,expected,cell))
            else:self.assertEqual(cell.get('v'),expected,(name,r+1,c+1))
        self.assertEqual(count,13104)
        self.assertEqual(len(formula_errors(data)),2)
        self.assertEqual(hashlib.sha256(Path(os.environ['WORKBOOK_PATH']).read_bytes()).hexdigest(),checksum)
