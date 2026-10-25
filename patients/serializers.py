from rest_framework import serializers

from patients.models import Assurance, Client, IndexRapprochement, Patient, PartageDossier, Telephone


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ("id_client", "nom", "prenom", "telephone_contact")
        read_only_fields = ("id_client",)


class PatientSerializer(serializers.ModelSerializer):
    telephones = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = (
            "id_patient", "nom_patient", "prenom_patient", "date_naissance", "sexe", "adresse",
            "numero_piece_identite", "allergies", "antecedents_medicaux", "id_assurance", "telephones",
        )
        read_only_fields = ("id_patient", "telephones")

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request and getattr(request.user, "role_metier", None) == "secretaire":
            fields.pop("allergies", None)
            fields.pop("antecedents_medicaux", None)
        return fields

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user.role_metier == "secretaire":
            if "allergies" in self.initial_data or "antecedents_medicaux" in self.initial_data:
                raise serializers.ValidationError("Le secrétariat ne peut pas consulter ni modifier les données médicales.")
        return attrs

    def get_telephones(self, obj):
        return TelephoneSerializer(obj.telephones.all(), many=True).data


class TelephoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Telephone
        fields = ("id_telephone", "numero_telephone", "type_telephone", "id_patient")
        read_only_fields = ("id_telephone",)


class AssuranceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assurance
        fields = ("id_assurance", "numero_police", "nom_assureur", "taux_prise_en_charge")
        read_only_fields = ("id_assurance",)


class PartageDossierSerializer(serializers.ModelSerializer):
    id_patient_source = serializers.UUIDField(source="id_patient_source_id", read_only=True)
    id_patient_destination = serializers.UUIDField(source="id_patient_destination_id", read_only=True)
    matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)

    class Meta:
        model = PartageDossier
        fields = (
            "id_partage", "date_partage", "id_patient_source", "id_patient_destination", "matricule_personnel",
        )
        read_only_fields = fields


class CorrespondanceSerializer(serializers.ModelSerializer):
    id_patient_source = serializers.UUIDField(source="id_patient_id", read_only=True)
    id_etablissement_source = serializers.UUIDField(source="id_etablissement_id", read_only=True)

    class Meta:
        model = IndexRapprochement
        fields = ("id_patient_source", "id_etablissement_source")
        read_only_fields = fields
