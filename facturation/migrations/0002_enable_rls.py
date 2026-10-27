from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):
    dependencies = [("facturation", "0001_initial")]

    operations = [
        enable_tenant_rls("facture"),
        enable_tenant_rls("ligne_facture"),
        enable_tenant_rls("paiement"),
    ]
