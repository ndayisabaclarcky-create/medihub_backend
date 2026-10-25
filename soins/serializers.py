from rest_framework import serializers

from soins.models import Acte, Chambre, Consultation, Hospitalisation, Lit, RendezVous


class RendezVousSerializer(serializers.ModelSerializer):
    id_patient = serializers.UUIDField(source="id_patient_id", read_only=True)
    matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)

    class Meta:
        model = RendezVous
        fields = (
            "id_rdv", "date_rendez_vous", "heure_rendez_vous", "statut_rendez_vous",
            "id_patient", "matricule_personnel",
        )
        read_only_fields = ("id_rdv", "statut_rendez_vous", "id_patient", "matricule_personnel")


class RendezVousCreateSerializer(serializers.Serializer):
    date_rendez_vous = serializers.DateField()
    heure_rendez_vous = serializers.TimeField()
    id_patient = serializers.UUIDField()
    matricule_personnel = serializers.UUIDField(required=False)


class ActeSerializer(serializers.ModelSerializer):
    id_patient = serializers.UUIDField(source="id_patient_id", read_only=True)

    class Meta:
        model = Acte
        fields = ("id_acte", "date_acte", "libelle_acte", "montant_base", "id_patient")
        read_only_fields = fields


class ConsultationSerializer(serializers.ModelSerializer):
    acte = ActeSerializer(source="id_acte", read_only=True)
    id_rendez_vous = serializers.UUIDField(source="id_rendez_vous_id", read_only=True)
    matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)
    matricule_interne = serializers.UUIDField(source="matricule_interne_id", read_only=True)

    class Meta:
        model = Consultation
        fields = (
            "id_acte", "acte", "diagnostic", "observations", "id_rendez_vous",
            "matricule_personnel", "matricule_interne", "statut_episode", "date_cloture_episode",
        )
        read_only_fields = fields


class ConsultationCreateSerializer(serializers.Serializer):
    id_patient = serializers.UUIDField()
    date_acte = serializers.DateField()
    libelle_acte = serializers.CharField(max_length=60)
    montant_base = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    diagnostic = serializers.CharField(max_length=200)
    observations = serializers.CharField(max_length=200, required=False, allow_blank=True, allow_null=True)
    id_rendez_vous = serializers.UUIDField(required=False, allow_null=True)
    matricule_interne = serializers.UUIDField(required=False, allow_null=True)


class ChambreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chambre
        fields = ("id_chambre", "numero_chambre", "type_chambre", "code_service")
        read_only_fields = ("id_chambre",)


class LitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lit
        fields = ("id_lit", "numero_lit", "id_chambre")
        read_only_fields = ("id_lit",)


class HospitalisationSerializer(serializers.ModelSerializer):
    id_patient = serializers.UUIDField(source="id_acte.id_patient_id", read_only=True)
    id_acte_consultation = serializers.UUIDField(source="id_acte_consultation_id", read_only=True)

    class Meta:
        model = Hospitalisation
        fields = (
            "id_acte", "id_patient", "date_entree", "date_sortie", "id_acte_consultation",
            "id_chambre", "id_lit",
        )
        read_only_fields = ("id_acte", "id_patient", "id_acte_consultation", "date_sortie")


class HospitalisationCreateSerializer(serializers.Serializer):
    id_acte_consultation = serializers.UUIDField()
    date_entree = serializers.DateField()
    date_acte = serializers.DateField()
    libelle_acte = serializers.CharField(max_length=60)
    montant_base = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    id_chambre = serializers.UUIDField(required=False, allow_null=True)
    id_lit = serializers.UUIDField(required=False, allow_null=True)


class AffectationLitSerializer(serializers.Serializer):
    id_chambre = serializers.UUIDField()
    id_lit = serializers.UUIDField(required=False, allow_null=True)
