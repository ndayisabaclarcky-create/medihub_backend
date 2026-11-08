from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):
    dependencies = [("equipements", "0001_initial")]

    operations = [
        enable_tenant_rls("equipement"),
        enable_tenant_rls("intervention_maintenance"),
    ]
