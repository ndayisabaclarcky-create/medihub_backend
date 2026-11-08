from rest_framework import serializers

from etablissements.models import Personnel
from partenariats.models import Partenariat


class PartenariatSerializer(serializers.ModelSerializer):
    id_etablissement = serializers.UUIDField(source="id_etablissement_id", read_only=True)
    id_etablissement_partenaire = serializers.UUIDField(source="id_etablissement_partenaire_id", read_only=True)
    nom_etablissement = serializers.CharField(source="id_etablissement.nom_etablissement", read_only=True)
    nom_etablissement_partenaire = serializers.CharField(
        source="id_etablissement_partenaire.nom_etablissement", read_only=True
    )
    matricule_proposant = serializers.UUIDField(source="matricule_proposant_id", read_only=True)
    matricule_validateur = serializers.UUIDField(source="matricule_validateur_id", read_only=True, allow_null=True)

    class Meta:
        model = Partenariat
        fields = (
            "id_partenariat", "id_etablissement", "nom_etablissement", "id_etablissement_partenaire",
            "nom_etablissement_partenaire", "type_partenariat", "date_debut", "date_fin", "statut",
            "description", "matricule_proposant", "matricule_validateur", "date_validation", "date_creation",
        )
        read_only_fields = fields


class PartenariatCreateSerializer(serializers.Serializer):
    id_etablissement_partenaire = serializers.UUIDField()
    type_partenariat = serializers.CharField(max_length=40)
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ActionPartenariatSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("accepter", "refuser", "terminer"))
