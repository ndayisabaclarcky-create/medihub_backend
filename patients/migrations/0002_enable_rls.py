from django.db import migrations

from core.db.rls import enable_tenant_rls


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0001_initial"),
    ]

    operations = [
        enable_tenant_rls("client"),
        enable_tenant_rls("patient"),
        enable_tenant_rls("telephone"),
        enable_tenant_rls("assurance"),
        enable_tenant_rls("index_rapprochement"),
        # partage_dossier : volontairement hors RLS (RG35-RG37, relie deux
        # établissements différents). Le filtrage devra être fait dans les
        # vues/serializers de l'API, pas au niveau base de données.
    ]
