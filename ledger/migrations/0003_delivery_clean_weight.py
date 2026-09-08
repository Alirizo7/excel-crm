from django.db import migrations


def rename_payload(apps, schema_editor):
    for batch in apps.get_model('ledger', 'ImportBatch').objects.all():
        for item in batch.payload.get('deliveries', []):
            if 'clean' in item:
                item['clean_weight'] = item.pop('clean')
        batch.save(update_fields=['payload'])


class Migration(migrations.Migration):
    dependencies = [('ledger', '0002_remove_operation_positive_operation_amount_and_more')]
    operations = [migrations.RenameField(model_name='delivery', old_name='clean', new_name='clean_weight'),
                  migrations.RunPython(rename_payload, migrations.RunPython.noop)]
