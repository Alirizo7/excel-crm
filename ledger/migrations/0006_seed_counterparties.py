import unicodedata
from django.db import migrations


def populate(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model('ledger', 'WorkspaceState').objects.using(db).get_or_create(pk=1)
    Partner = apps.get_model('ledger', 'Counterparty')
    Balance = apps.get_model('ledger', 'PartnerBalance')
    for balance in Balance.objects.using(db).all().iterator():
        name = ' '.join(balance.name.split())
        partner, _ = Partner.objects.using(db).get_or_create(
            key=unicodedata.normalize('NFKC', name).casefold(), defaults={'name': name})
        Balance.objects.using(db).filter(pk=balance.pk).update(counterparty=partner)


class Migration(migrations.Migration):
    dependencies = [('ledger', '0005_counterparty_debtpayment_recordchange_workspacestate_and_more')]
    operations = [migrations.RunPython(populate, migrations.RunPython.noop)]
