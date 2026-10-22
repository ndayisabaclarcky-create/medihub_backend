from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):

    dependencies = [
        ("soins", "0001_initial"),
    ]

    operations = [
        enable_tenant_rls("rendez_vous"),
        enable_tenant_rls("acte"),
        enable_tenant_rls("consultation"),
        enable_tenant_rls("hospitalisation"),
        enable_tenant_rls("chambre"),
        enable_tenant_rls("lit"),
    ]