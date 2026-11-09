from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0005_patient_groupe_sanguin_patient_medecin_referent_and_more"),
    ]

    operations = [
        enable_tenant_rls("mesure_poids_patient"),
    ]
