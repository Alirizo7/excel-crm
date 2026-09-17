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

    def test_admin_creates_company_with_owner_login_and_password(self):
        self.client.force_login(get_user_model().objects.get(username='admin'))
        response = self.client.post(reverse('admin:ledger_workspace_add'), {
            'name': 'Новая компания',
            'is_active': 'on',
            'owner_username': 'new-owner',
            'owner_password': 'Client-password-4782',
            '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='new-owner')
        membership = WorkspaceMembership.objects.select_related('workspace').get(user=user)
        self.assertEqual(membership.workspace.name, 'Новая компания')
        self.assertTrue(membership.workspace.is_active)
        self.assertTrue(user.check_password('Client-password-4782'))
        self.assertFalse(ImportBatch.objects.filter(workspace=membership.workspace).exists())

        change_list = reverse('admin:ledger_workspace_changelist')
        self.assertContains(self.client.get(change_list), 'Приостановить выбранные компании')
        self.client.post(change_list, {
            'action': 'suspend_companies',
            '_selected_action': membership.workspace.pk,
            'index': '0',
        })
        membership.workspace.refresh_from_db()
        self.assertFalse(membership.workspace.is_active)
        self.client.post(change_list, {
            'action': 'activate_companies',
            '_selected_action': membership.workspace.pk,
            'index': '0',
        })
        membership.workspace.refresh_from_db()
        self.assertTrue(membership.workspace.is_active)

        client = Client()
        response = client.post(reverse('login'), {
            'username': 'new-owner', 'password': 'Client-password-4782',
        })
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertRedirects(client.get(reverse('home')), reverse('imports'))
        self.assertContains(client.get(reverse('imports')), 'Загрузите ваш рабочий Excel один раз')

    def test_superuser_keeps_admin_access_when_default_company_is_suspended(self):
        admin_user = get_user_model().objects.get(username='admin')
        membership = WorkspaceMembership.objects.get(user=admin_user)
        membership.workspace.is_active = False
        membership.workspace.save(update_fields=['is_active'])
        self.client.force_login(admin_user)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)

    def test_public_registration_is_not_available(self):
        response = self.client.get('/register/')
        self.assertRedirects(response, reverse('login') + '?next=/register/')
        self.assertNotContains(self.client.get(reverse('login')), 'Создать компанию')

    def test_suspended_company_loses_access_and_can_be_reactivated(self):
        _, workspace, client = self.make_company('suspended-owner', 'Компания без оплаты')
        self.assertEqual(client.get(reverse('operations')).status_code, 200)

        workspace.is_active = False
        workspace.save(update_fields=['is_active'])
        self.assertRedirects(client.get(reverse('operations')), reverse('company_suspended'))
        self.assertContains(client.get(reverse('company_suspended')), 'Доступ компании приостановлен')

        fresh_client = Client()
        response = fresh_client.post(reverse('login'), {
            'username': 'suspended-owner', 'password': 'safe-password-4782',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Доступ компании временно приостановлен')
        self.assertNotIn('_auth_user_id', fresh_client.session)

        workspace.is_active = True
        workspace.save(update_fields=['is_active'])
        self.assertEqual(client.get(reverse('operations')).status_code, 200)
        response = fresh_client.post(reverse('login'), {
            'username': 'suspended-owner', 'password': 'safe-password-4782',
        })
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

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
