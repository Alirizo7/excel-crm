from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from .models import ImportBatch, Operation, Workspace, WorkspaceMembership
from .services.importing import commit_import, stage_import
from .tests import legacy_bytes


class WorkspaceIsolationTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media.cleanup)

    def make_company(self, username, company):
        user = get_user_model().objects.create_user(username, password='safe-password-4782')
        workspace = Workspace.objects.create(name=company)
        WorkspaceMembership.objects.create(user=user, workspace=workspace)
        client = Client()
        client.force_login(user)
        return user, workspace, client

    def test_registration_creates_an_empty_private_company(self):
        response = self.client.post(reverse('register'), {
            'company_name': '  Новая   компания  ',
            'username': 'new-owner',
            'password1': 'Safe-password-4782',
            'password2': 'Safe-password-4782',
        })
        self.assertRedirects(response, reverse('imports'))
        user = get_user_model().objects.get(username='new-owner')
        membership = WorkspaceMembership.objects.select_related('workspace').get(user=user)
        self.assertEqual(membership.workspace.name, 'Новая компания')
        self.assertFalse(ImportBatch.objects.filter(workspace=membership.workspace).exists())
        self.assertRedirects(self.client.get(reverse('home')), reverse('imports'))
        self.assertContains(self.client.get(reverse('imports')), 'Загрузите ваш рабочий Excel один раз')

    def test_user_created_outside_registration_gets_a_separate_company(self):
        first = Workspace.objects.order_by('pk').first()
        user = get_user_model().objects.create_user('external-user', password='safe-password-4782')
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get(reverse('home')).status_code, 302)
        membership = WorkspaceMembership.objects.get(user=user)
        self.assertNotEqual(membership.workspace, first)
        self.assertEqual(membership.workspace.name, 'external-user')

    def test_records_imports_and_exports_are_isolated(self):
        _, first, first_client = self.make_company('owner-a', 'Компания А')
        _, second, second_client = self.make_company('owner-b', 'Компания Б')
        first_item = Operation.objects.create(
            workspace=first, date=date(2026, 9, 1), kind='income', amount=101,
            description='Только компания А', category='Прочее',
        )
        Operation.objects.create(
            workspace=second, date=date(2026, 9, 2), kind='income', amount=202,
            description='Только компания Б', category='Прочее',
        )

        first_page = first_client.get(reverse('operations'))
        self.assertContains(first_page, 'Только компания А')
        self.assertNotContains(first_page, 'Только компания Б')
        self.assertEqual(second_client.get(reverse('record_detail', args=['operations', first_item.pk])).status_code, 404)

        exported = second_client.get(reverse('export_download', args=['operations']))
        rows = list(load_workbook(BytesIO(exported.content), data_only=True).active.values)
        self.assertTrue(any('Только компания Б' in row for row in rows))
        self.assertFalse(any('Только компания А' in row for row in rows))

        data = legacy_bytes()
        first_batch, first_created = stage_import(data, 'first.xlsx', workspace=first)
        second_batch, second_created = stage_import(data, 'second.xlsx', workspace=second)
        self.assertTrue(first_created and second_created)
        self.assertNotEqual(first_batch.pk, second_batch.pk)
        commit_import(first_batch.pk, workspace=first)
        commit_import(second_batch.pk, workspace=second)
        self.assertEqual(first_client.get(reverse('import_detail', args=[second_batch.pk])).status_code, 404)
        self.assertEqual(first_client.get(reverse('source_download', args=[second_batch.pk])).status_code, 404)
