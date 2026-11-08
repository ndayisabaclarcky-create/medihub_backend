from rest_framework import serializers

from equipements.models import Equipement, InterventionMaintenance


class EquipementSerializer(serializers.ModelSerializer):
    id_etablissement = serializers.UUIDField(source="id_etablissement_id", read_only=True)
    code_service = serializers.UUIDField(source="code_service_id", required=False, allow_null=True)

    class Meta:
        model = Equipement
        fields = (
            "id_equipement", "id_etablissement", "code_equipement", "nom", "categorie", "fabricant", "modele",
            "numero_serie", "emplacement", "code_service", "date_acquisition", "date_mise_en_service",
            "date_fin_garantie", "etat", "date_creation",
        )
        read_only_fields = ("id_equipement", "id_etablissement", "date_creation")


class InterventionMaintenanceSerializer(serializers.ModelSerializer):
    id_etablissement = serializers.UUIDField(source="id_etablissement_id", read_only=True)
    id_equipement = serializers.UUIDField(source="id_equipement_id")
    matricule_technicien = serializers.UUIDField(source="matricule_technicien_id", required=False, allow_null=True)

    class Meta:
        model = InterventionMaintenance
        fields = (
            "id_intervention", "id_etablissement", "id_equipement", "type_intervention", "statut",
            "date_planifiee", "date_realisation", "description", "cout", "matricule_technicien",
            "prochaine_echeance", "date_creation",
        )
        read_only_fields = ("id_intervention", "id_etablissement", "date_creation")
