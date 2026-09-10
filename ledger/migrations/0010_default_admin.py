from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations


def create_default_admin(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    User.objects.using(schema_editor.connection.alias).get_or_create(
        username='admin',
        defaults={
            'password': make_password('admin123'),
            'is_active': True,
            'is_staff': True,
            'is_superuser': True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ledger', '0009_workingworkbook_workbookversion'),
    ]

    operations = [
        migrations.RunPython(create_default_admin, migrations.RunPython.noop),
    ]
