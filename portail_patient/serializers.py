from rest_framework import serializers

from soins.models import RendezVous


class DemandeCodeSerializer(serializers.Serializer):
    id_hopital = serializers.UUIDField()
    numero_telephone = serializers.CharField(max_length=20, trim_whitespace=True)


class VerifierCodeSerializer(DemandeCodeSerializer):
    code = serializers.RegexField(r"^\d{6}$", max_length=6, min_length=6)


class MedecinPortailSerializer(serializers.Serializer):
    matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)
    nom = serializers.CharField(source="matricule_personnel.nom", read_only=True)
    prenom = serializers.CharField(source="matricule_personnel.prenom", read_only=True)
    specialite = serializers.CharField(read_only=True)


class RendezVousPortailSerializer(serializers.ModelSerializer):
    medecin = serializers.SerializerMethodField()

    class Meta:
        model = RendezVous
        fields = ("id_rdv", "date_rendez_vous", "heure_rendez_vous", "statut_rendez_vous", "medecin")
        read_only_fields = fields

    def get_medecin(self, obj):
        personnel = obj.matricule_personnel.matricule_personnel
        return {
            "matricule_personnel": str(personnel.pk),
            "nom": personnel.nom,
            "prenom": personnel.prenom,
            "specialite": obj.matricule_personnel.specialite,
        }


class PrendreRendezVousSerializer(serializers.Serializer):
    matricule_personnel = serializers.UUIDField()
    date_rendez_vous = serializers.DateField()
    heure_rendez_vous = serializers.TimeField()


class DisponibiliteSerializer(PrendreRendezVousSerializer):
    pass
