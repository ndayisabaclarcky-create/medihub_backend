from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):

    dependencies = [
        ("etablissements", "0001_initial"),
    ]

    operations = [
        enable_tenant_rls("service"),
        enable_tenant_rls("affectation"),
        enable_tenant_rls("journal_action"),
    ]