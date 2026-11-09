from rest_framework import serializers

from etablissements.models import Medecin
from patients.models import Assurance, Client, IndexRapprochement, MesurePoids, Patient, PartageDossier, Telephone


class MesurePoidsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MesurePoids
        fields = ("id_mesure_poids", "poids_kg", "date_mesure")
        read_only_fields = ("id_mesure_poids", "date_mesure")


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ("id_client", "nom", "prenom", "telephone_contact")
        read_only_fields = ("id_client",)


class PatientSerializer(serializers.ModelSerializer):
    telephones = serializers.SerializerMethodField()
    mesures_poids = MesurePoidsSerializer(many=True, read_only=True)
    historiques_medicaux_recus = serializers.SerializerMethodField()
    medecin_referent = serializers.PrimaryKeyRelatedField(
        queryset=Medecin.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Patient
        fields = (
            "id_patient", "nom_patient", "prenom_patient", "date_naissance", "sexe", "adresse",
            "numero_piece_identite", "allergies", "antecedents_medicaux", "groupe_sanguin",
            "medecin_referent", "id_assurance", "telephones", "mesures_poids", "historiques_medicaux_recus",
        )
        read_only_fields = ("id_patient", "telephones")

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            fields["medecin_referent"].queryset = Medecin.objects.filter(
                matricule_personnel__id_etablissement_id=request.user.id_etablissement_id,
                matricule_personnel__role_metier="medecin",
            )
        if request and getattr(request.user, "role_metier", None) == "secretaire":
            fields.pop("allergies", None)
            fields.pop("antecedents_medicaux", None)
            fields.pop("groupe_sanguin", None)
            fields.pop("medecin_referent", None)
            fields.pop("mesures_poids", None)
            fields.pop("historiques_medicaux_recus", None)
        return fields

    def validate(self, attrs):
        request = self.context.get("request")
        medecin = attrs.get("medecin_referent")
        if medecin and request and medecin.matricule_personnel.id_etablissement_id != request.user.id_etablissement_id:
            raise serializers.ValidationError(
                {"medecin_referent": "Le médecin référent doit exercer dans cet hôpital."}
            )
        if request and request.user.role_metier == "secretaire":
            champs_medicaux = {
                "allergies", "antecedents_medicaux", "groupe_sanguin", "medecin_referent", "mesures_poids", "historiques_medicaux_recus"
            }
            if champs_medicaux.intersection(self.initial_data):
                raise serializers.ValidationError("Le secrétariat ne peut pas consulter ni modifier les données médicales.")
        return attrs

    def get_historiques_medicaux_recus(self, patient):
        return [
            {
                "id_historique_partage": str(historique.pk),
                "date_consentement": historique.date_consentement,
                "hopital_source": str(historique.id_etablissement_source),
                "resume_medical": historique.resume_medical,
                "documents": [
                    {"id_document_partage": str(document.pk), "type_document": document.type_document_source,
                     "titre": document.titre, "date_document": document.date_document}
                    for document in historique.documents.all()
                ],
            }
            for historique in patient.historiques_medicaux_recus.prefetch_related("documents").all()
        ]

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
