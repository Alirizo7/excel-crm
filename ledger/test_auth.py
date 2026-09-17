from importlib import import_module
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import DebtPayment, Operation
from .urls import urlpatterns


class WorkspaceAuthenticationTests(TestCase):
    def test_migrations_create_default_admin_on_a_fresh_database(self):
        user = get_user_model().objects.get(username='admin')
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertNotEqual(user.password, 'admin123')
        self.assertTrue(self.client.login(username='admin', password='admin123'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)

    def test_bootstrap_preserves_an_existing_account_and_changed_password(self):
        user = get_user_model().objects.get(username='admin')
        user.set_password('changed-by-owner-5678')
        user.is_staff = False
        user.save()
        seed = import_module('ledger.migrations.0010_default_admin').create_default_admin
        seed(apps, SimpleNamespace(connection=connection))
        user.refresh_from_db()
        self.assertTrue(user.check_password('changed-by-owner-5678'))
        self.assertFalse(user.check_password('admin123'))
        self.assertFalse(user.is_staff)
        self.assertEqual(get_user_model().objects.filter(username='admin').count(), 1)

    def test_all_workspace_routes_require_login_for_reading_and_writing(self):
        for pattern in urlpatterns:
            kwargs = {
                name: 'operations' if name == 'kind' else 1
                for name in pattern.pattern.converters
            }
            url = reverse(pattern.name, kwargs=kwargs)
            for method in ('get', 'post'):
                with self.subTest(route=pattern.name, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 302)
                    destination = urlsplit(response['Location'])
                    self.assertEqual(destination.path, reverse('login'))
                    self.assertEqual(parse_qs(destination.query)['next'], [url])
        self.assertEqual(Operation.objects.count(), 0)
        self.assertEqual(DebtPayment.objects.count(), 0)

    @override_settings(DEBUG=True, LOCAL_WORKSPACE=True)
    def test_debug_loopback_and_old_local_setting_cannot_bypass_login(self):
        for address in ('127.0.0.1', '::1', '192.0.2.1'):
            with self.subTest(address=address):
                self.assertEqual(self.client.get('/', REMOTE_ADDR=address).status_code, 302)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)
        self.assertEqual(self.client.get('/media/private.xlsx').status_code, 302)

    def test_login_and_logout_with_csrf_return_to_requested_page(self):
        client = Client(enforce_csrf_checks=True)
        target = reverse('operations') + '?kind=income'
        response = client.get(target)
        login_url = response['Location']
        response = client.get(login_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('current_batch', response.context)
        credentials = {'username': 'admin', 'password': 'admin123', 'next': target}
        self.assertEqual(client.post(reverse('login'), credentials).status_code, 403)
        response = client.post(reverse('login'), {
            **credentials, 'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        })
        self.assertRedirects(response, target)
        self.assertRedirects(client.get(reverse('login')), reverse('home'), fetch_redirect_response=False)
        self.assertEqual(client.get(reverse('logout')).status_code, 405)
        self.assertEqual(client.post(reverse('logout')).status_code, 403)
        self.assertRedirects(client.post(reverse('logout'), {
            'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        }), reverse('login'))
        self.assertEqual(client.get(target).status_code, 302)

    def test_incorrect_password_and_inactive_account_are_rejected(self):
        response = self.client.post(reverse('login'), {'username': 'admin', 'password': 'wrong-password'})
        self.assertContains(response, 'Проверьте имя пользователя и пароль.')
        self.assertNotIn('_auth_user_id', self.client.session)
        get_user_model().objects.filter(username='admin').update(is_active=False)
        response = self.client.post(reverse('login'), {'username': 'admin', 'password': 'admin123'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_does_not_redirect_to_an_external_site(self):
        for target in ('https://example.com/private', '//example.com/private'):
            with self.subTest(target=target):
                client = Client()
                response = client.post(reverse('login'), {
                    'username': 'admin', 'password': 'admin123', 'next': target,
                })
                self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
