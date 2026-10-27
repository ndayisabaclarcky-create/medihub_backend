from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):
    dependencies = [("portail_patient", "0001_initial")]

    operations = [enable_tenant_rls("code_verification")]
