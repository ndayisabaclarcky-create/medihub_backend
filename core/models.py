"""
Briques abstraites partagées par tous les blocs du dictionnaire de données.
"""
import uuid

from django.db import models


def uuid_pk_field():
    """
    Fabrique un champ UUID à utiliser comme clé primaire. Le nom du champ
    (matricule_personnel, id_patient, id_rdv...) est choisi individuellement
    dans chaque modèle pour rester fidèle au dictionnaire de données, plutôt
    que d'imposer un "id" générique.
    """
    return models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)


class EtablissementScopedModel(models.Model):
    """
    Base abstraite pour toute table portant directement id_etablissement.
    """
    id_etablissement = models.ForeignKey(
        "etablissements.Etablissement",
        on_delete=models.PROTECT,
        db_column="id_etablissement",
    )

    class Meta:
        abstract = True