from datetime import date
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from openpyxl import load_workbook

from .forms import DeliveryForm
from .i18n import localize_system_text
from .models import Delivery, Operation, SourceSheet
from .services.exporting import make_export
from .services.importing import commit_import, inspect_workbook, stage_import
from .tests import legacy_bytes


class InterfaceLanguageTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.get(username='admin'))
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def use_uzbek(self):
        return self.client.post(reverse('set_language'), {'language': 'uz', 'next': '/'})

    def test_switch_keeps_filters_and_persists_across_pages(self):
        item = Operation.objects.create(date=date(2026, 9, 1), kind='income', amount=100,
                                        description='Металл', category='Прочее')
        url = reverse('operations') + '?kind=income&category=%D0%9F%D1%80%D0%BE%D1%87%D0%B5%D0%B5'
        response = self.client.post(reverse('set_language'), {'language': 'uz', 'next': url})
        self.assertEqual(response['Location'], url)
        self.assertEqual(response.cookies['django_language'].value, 'uz')
        self.assertGreater(int(response.cookies['django_language']['max-age']), 0)
        response = self.client.get(url)
        self.assertContains(response, '<html lang="uz">')
        self.assertContains(response, 'Pul operatsiyalari')
        self.assertContains(response, '<option value="income" selected>Kirim</option>', html=True)
        self.assertContains(response, '<option value="Прочее" selected>Boshqa</option>', html=True)
        self.assertEqual(list(response.context['page']), [item])
        self.assertContains(self.client.get(reverse('record_detail', args=['operations', item.pk])), 'Металл')
        item.refresh_from_db()
        self.assertEqual(item.category, 'Прочее')
        self.assertContains(self.client.get(reverse('exports'), follow=True), 'Umumiy ko‘rinish')
        self.client.post(reverse('set_language'), {'language': 'ru', 'next': '/'})
        response = self.client.get('/', follow=True)
        self.assertContains(response, '<html lang="ru">')
        self.assertContains(response, 'Загрузить Excel')

    def test_uzbek_pages_and_saved_import_issues(self):
        batch, _ = stage_import(legacy_bytes(), '01.09.2026.xlsx')
        commit_import(batch.pk)
        self.use_uzbek()
        for route in ['dashboard', 'operations', 'deliveries', 'partners', 'imports', 'exports', 'sheets', 'help', 'operation_new', 'delivery_new']:
            with self.subTest(route=route):
                response = self.client.get(reverse(route), follow=True)
                self.assertContains(response, '<html lang="uz">')
                self.assertNotContains(response, 'Рабочее пространство')
        response = self.client.get(reverse('import_detail', args=[batch.pk]))
        self.assertContains(response, 'Tekshirish natijalari')
        self.assertContains(response, '1,000.00 UZS tuzatish')
        self.assertContains(response, 'Asosiy pul operatsiyalari jurnali')
        source = SourceSheet.objects.get(batch=batch, name='Приход-Расход')
        self.assertContains(self.client.get(reverse('sheet_detail', args=[source.pk])), 'Продажа')
        self.assertContains(self.client.get(reverse('record_detail', args=['deliveries', Delivery.objects.get().pk])), 'Jo‘natish')
        batch.refresh_from_db()
        self.assertTrue(any('корректировка' in issue['message'] for issue in batch.issues))

    def test_uzbek_validation_and_import_errors(self):
        self.use_uzbek()
        response = self.client.post(reverse('operation_new'), {
            'date': '2026-09-01', 'kind': 'income', 'amount': '0',
            'description': 'Сохранить как есть', 'category': 'Прочее',
        })
        self.assertContains(response, 'Operatsiya summasi nol bo‘lishi mumkin emas.')
        self.assertEqual(Operation.objects.count(), 0)
        response = self.client.post(reverse('imports'), {'file': SimpleUploadedFile('broken.xlsx', b'not a workbook')})
        self.assertContains(response, 'Excel faylini o‘qib bo‘lmadi.')
        with translation.override('uz'):
            form = DeliveryForm({'date': '2026-09-01', 'direction': 'in', 'partner': 'A',
                'vehicle': '919', 'gross': 10, 'tare': 11, 'discount': 101, 'price': 100})
            self.assertFalse(form.is_valid())
            self.assertIn('Tara brutto vaznidan oshmasligi kerak.', form.errors['tare'])
            self.assertIn('Qiymat 100 dan katta bo‘lmasligi kerak.', form.errors['discount'])
            self.assertEqual(localize_system_text('Строка 2: некорректная дата'), '2-qator: sana noto‘g‘ri')
            self.assertIn('94 ta pul operatsiyasida sana yo‘q', localize_system_text(
                '94 денежных операций без даты. Они входят в общий итог, но не в отчёты за период.'))
            self.assertIn('Excel xatosi #REF!', localize_system_text(
                'Ошибка Excel #REF!. Исходная формула сохранена; значение исключено из расчётов.'))

    def test_uzbek_export_remains_compatible_with_reimport(self):
        Operation.objects.create(date=date(2026, 9, 1), kind='income', amount=Decimal('-25.50'),
                                 description='Исходный текст', category='Прочее')
        Delivery.objects.create(date=date(2026, 9, 1), direction='in', partner='Феруз', vehicle='919',
                                gross=100, tare=20, discount=1, price=3500)
        self.use_uzbek()
        response = self.client.get(reverse('export_download', args=['report']))
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(book['Операции']['C2'].value, 'Приход')
        self.assertEqual(book['Поставки']['C2'].value, 'Приёмка')
        self.assertEqual(book['Операции']['E2'].value, 'Исходный текст')
        with translation.override('uz'):
            for kind in ['operations', 'deliveries']:
                data = make_export(kind, operations=Operation.objects.all(), deliveries=Delivery.objects.all())
                result = inspect_workbook(data, kind + '.xlsx')
                self.assertEqual(result['summary']['errors'], 0)
                self.assertTrue(any('ID уже существует' in issue['message'] for issue in result['issues']))
            self.assertEqual(translation.get_language(), 'uz')

    def test_language_can_be_changed_on_login_with_csrf(self):
        client = Client(enforce_csrf_checks=True)
        next_url = reverse('login') + '?next=%2Fexports%2F'
        client.get(next_url)
        self.assertEqual(client.post(reverse('set_language'), {'language': 'uz'}).status_code, 403)
        response = client.post(reverse('set_language'), {'language': 'uz', 'next': next_url,
                               'csrfmiddlewaretoken': client.cookies['csrftoken'].value})
        self.assertEqual(response['Location'], next_url)
        response = client.get(next_url)
        self.assertContains(response, 'Foydalanuvchi nomi')
        self.assertContains(response, 'Parol')
        self.assertContains(response, '<html lang="uz">')
        self.assertEqual(client.get('/').status_code, 302)
