from rest_framework import serializers

from django.contrib.auth.password_validation import validate_password

from patients.models import ComptePatient, Patient
from soins.models import RendezVous


class DemandeCodeSerializer(serializers.Serializer):
    id_hopital = serializers.UUIDField()
    numero_telephone = serializers.CharField(max_length=20, trim_whitespace=True)


class VerifierCodeSerializer(DemandeCodeSerializer):
    code = serializers.RegexField(r"^\d{6}$", max_length=6, min_length=6)


class InscriptionComptePatientSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, validators=[validate_password])
    allergies_declarees = serializers.CharField(required=False, allow_blank=True, max_length=500)
    antecedents_declares = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    groupe_sanguin_declare = serializers.ChoiceField(choices=("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"), required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = ComptePatient
        fields = (
            "identifiant_connexion", "nom", "prenom", "date_naissance", "sexe",
            "numero_telephone", "password", "allergies_declarees", "antecedents_declares", "groupe_sanguin_declare",
        )

    def validate_identifiant_connexion(self, value):
        value = value.strip().lower()
        if ComptePatient.objects.filter(identifiant_connexion__iexact=value).exists():
            raise serializers.ValidationError("Cet identifiant est déjà utilisé.")
        return value

    def validate_numero_telephone(self, value):
        value = value.strip().replace(" ", "")
        if ComptePatient.objects.filter(numero_telephone=value).exists():
            raise serializers.ValidationError("Ce numéro est déjà associé à un compte.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        compte = ComptePatient(**validated_data)
        compte.set_password(password)
        compte.full_clean()
        compte.save()
        return compte


class ConnexionComptePatientSerializer(serializers.Serializer):
    identifiant_connexion = serializers.CharField(max_length=50)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class VerificationComptePatientSerializer(serializers.Serializer):
    id_code = serializers.UUIDField()
    code = serializers.RegexField(r"^\d{6}$", max_length=6, min_length=6)


class RendezVousNouveauHopitalSerializer(serializers.Serializer):
    matricule_personnel = serializers.UUIDField()
    date_rendez_vous = serializers.DateField()
    heure_rendez_vous = serializers.TimeField()


class DocumentPartageChoisiSerializer(serializers.Serializer):
    type_document = serializers.ChoiceField(choices=(
        ("resultat_examen", "Résultat"),
        ("prescription", "Prescription"),
        ("facture", "Facture"),
    ))
    id_document = serializers.UUIDField()


class PartagerHistoriqueSerializer(serializers.Serializer):
    id_hopital_source = serializers.UUIDField()
    id_hopital_destination = serializers.UUIDField()
    consentement = serializers.BooleanField()
    documents = DocumentPartageChoisiSerializer(many=True, max_length=10, required=False)

    def validate(self, attrs):
        if not attrs["consentement"]:
            raise serializers.ValidationError({"consentement": "Le consentement explicite est obligatoire."})
        if attrs["id_hopital_source"] == attrs["id_hopital_destination"]:
            raise serializers.ValidationError("Choisissez deux hôpitaux différents.")
        keys = [(doc["type_document"], doc["id_document"]) for doc in attrs.get("documents", [])]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError({"documents": "Un même document ne peut être sélectionné deux fois."})
        return attrs


class ProfilPatientSerializer(serializers.ModelSerializer):
    nom = serializers.CharField(source="nom_patient", read_only=True)
    prenom = serializers.CharField(source="prenom_patient", read_only=True)
    medecin_referent = serializers.SerializerMethodField()
    mesures_poids = serializers.SerializerMethodField()
    historiques_partages = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = (
            "id_patient", "nom", "prenom", "allergies", "antecedents_medicaux",
            "groupe_sanguin", "medecin_referent", "mesures_poids", "historiques_partages",
        )
        read_only_fields = fields

    def get_medecin_referent(self, patient):
        medecin = patient.medecin_referent
        if not medecin:
            return None
        personnel = medecin.matricule_personnel
        return {
            "nom": personnel.nom,
            "prenom": personnel.prenom,
            "specialite": medecin.specialite,
            "photo_profil": medecin.photo_profil.url if medecin.photo_profil else None,
        }

    def get_mesures_poids(self, patient):
        return [
            {"poids_kg": mesure.poids_kg, "date_mesure": mesure.date_mesure}
            for mesure in patient.mesures_poids.all()
        ]

    def get_historiques_partages(self, patient):
        return [
            {
                "id_historique_partage": str(historique.pk),
                "id_etablissement_source": str(historique.id_etablissement_source),
                "date_consentement": historique.date_consentement,
                "resume_medical": historique.resume_medical,
                "documents": [
                    {
                        "id_document_partage": str(document.pk),
                        "type_document": document.type_document_source,
                        "titre": document.titre,
                        "date_document": document.date_document,
                    }
                    for document in historique.documents.all()
                ],
            }
            for historique in patient.historiques_medicaux_recus.prefetch_related("documents").all()
        ]


class MedecinPortailSerializer(serializers.Serializer):
    matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)
    nom = serializers.CharField(source="matricule_personnel.nom", read_only=True)
    prenom = serializers.CharField(source="matricule_personnel.prenom", read_only=True)
    specialite = serializers.CharField(read_only=True)
    photo_profil = serializers.ImageField(read_only=True)


class RendezVousPortailSerializer(serializers.ModelSerializer):
    medecin = serializers.SerializerMethodField()

    class Meta:
        model = RendezVous
        fields = ("id_rdv", "date_rendez_vous", "heure_rendez_vous", "statut_rendez_vous", "motif_refus", "motif", "medecin")
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


class DisponibilitesJourSerializer(serializers.Serializer):
    matricule_personnel = serializers.UUIDField()
    date_rendez_vous = serializers.DateField()
