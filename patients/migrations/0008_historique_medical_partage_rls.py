from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0007_comptepatient_codecomptepatient_and_more"),
    ]

    operations = [
        enable_tenant_rls("historique_medical_partage"),
        enable_tenant_rls("document_medical_partage"),
    ]
