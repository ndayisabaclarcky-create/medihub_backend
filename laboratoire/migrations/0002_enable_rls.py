from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):
    dependencies = [("laboratoire", "0001_initial")]

    operations = [
        enable_tenant_rls("examen"),
        enable_tenant_rls("examen_prescrit"),
        enable_tenant_rls("resultat_examen"),
        enable_tenant_rls("notification"),
    ]
