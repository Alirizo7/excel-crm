from django.db import migrations
from django.utils import timezone


def populate(apps, schema_editor):
    for name in ['Operation', 'Delivery', 'PartnerBalance']:
        apps.get_model('ledger', name).objects.using(schema_editor.connection.alias).filter(
            batch__status='superseded', active=False).update(archived_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [('ledger', '0007_delivery_archived_at_operation_archived_at_and_more')]
    operations = [migrations.RunPython(populate, migrations.RunPython.noop)]
