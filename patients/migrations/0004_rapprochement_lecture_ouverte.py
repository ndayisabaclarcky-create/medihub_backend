from django.db import migrations

from core.db.rls import open_select_policy


class Migration(migrations.Migration):
    """
    Option B (RG35, Processus 3) : index_rapprochement garde sa policy
    tenant_isolation_* (0002) pour les écritures, et reçoit une seconde policy
    permissive FOR SELECT qui ouvre la LECTURE à tous les établissements.
    Sans elle, l'hôpital B ne verrait que ses propres lignes et ne pourrait
    jamais découvrir qu'un patient est déjà connu de l'hôpital A.
    """

    dependencies = [
        ("patients", "0003_contraintes_partage_et_taux"),
    ]

    operations = [
        open_select_policy("index_rapprochement"),
    ]
