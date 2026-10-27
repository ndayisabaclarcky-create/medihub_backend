from rest_framework import serializers

from laboratoire.models import Examen, ExamenPrescrit, Notification, ResultatExamen


class ExamenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Examen
        fields = ("id_examen", "code_examen", "libelle_examen", "tarif")
        read_only_fields = ("id_examen",)


class PrescrireExamensSerializer(serializers.Serializer):
    id_acte_consultation = serializers.UUIDField()
    codes_examens = serializers.ListField(
        child=serializers.CharField(max_length=20), allow_empty=False, max_length=50
    )


class ResultatExamenSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResultatExamen
        fields = ("id_resultat", "contenu_resultat", "date_disponibilite")
        read_only_fields = fields


class ExamenPrescritSerializer(serializers.ModelSerializer):
    id_patient = serializers.UUIDField(source="id_acte.id_patient_id", read_only=True)
    id_acte_consultation = serializers.UUIDField(source="id_acte_consultation_id", read_only=True)
    code_examen = serializers.CharField(source="id_examen.code_examen", read_only=True)
    libelle_examen = serializers.CharField(source="id_examen.libelle_examen", read_only=True)
    matricule_medecin_prescripteur = serializers.UUIDField(
        source="matricule_medecin_prescripteur_id", read_only=True
    )
    matricule_technicien = serializers.UUIDField(source="matricule_technicien_id", read_only=True, allow_null=True)
    resultat = ResultatExamenSerializer(read_only=True)

    class Meta:
        model = ExamenPrescrit
        fields = (
            "id_acte", "id_patient", "id_acte_consultation", "id_examen", "code_examen", "libelle_examen",
            "date_prescription_examen", "date_realisation", "matricule_medecin_prescripteur",
            "matricule_technicien", "resultat",
        )
        read_only_fields = fields


class ResultatCreateSerializer(serializers.Serializer):
    contenu_resultat = serializers.CharField(max_length=300, required=False, allow_blank=True, allow_null=True)


class NotificationSerializer(serializers.ModelSerializer):
    id_resultat_examen = serializers.UUIDField(source="id_resultat_examen_id", read_only=True, allow_null=True)

    class Meta:
        model = Notification
        fields = (
            "id_notification", "type_notification", "contenu", "date_creation", "lue", "date_lecture",
            "id_resultat_examen",
        )
        read_only_fields = fields
