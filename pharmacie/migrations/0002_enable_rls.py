from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacie", "0001_initial"),
    ]

    operations = [
        enable_tenant_rls("medicament"),
        enable_tenant_rls("lot_medicament"),
        enable_tenant_rls("prescription"),
        enable_tenant_rls("ligne_prescription"),
        enable_tenant_rls("vente"),
        enable_tenant_rls("ligne_vente"),
    ]
