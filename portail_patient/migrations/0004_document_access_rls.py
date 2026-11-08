from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):
    dependencies = [("portail_patient", "0003_accesdocumentpatient")]

    operations = [enable_tenant_rls("acces_document_patient")]
