from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from etablissements.models import Affectation, Etablissement, Hopital, Medecin, Personnel, Pharmacie, Service


class EtablissementSerializer(serializers.ModelSerializer):
    numero_agrement = serializers.SerializerMethodField()
    type_hopital = serializers.SerializerMethodField()
    id_etablissement_hopital_rattachement = serializers.SerializerMethodField()

    class Meta:
        model = Etablissement
        fields = (
            "id_etablissement", "nom_etablissement", "type_etablissement", "adresse",
            "telephone_contact", "email_contact", "date_creation_compte", "numero_agrement",
            "type_hopital", "id_etablissement_hopital_rattachement",
        )
        read_only_fields = fields

    def get_numero_agrement(self, obj):
        return getattr(getattr(obj, "hopital", None), "numero_agrement", None)

    def get_type_hopital(self, obj):
        return getattr(getattr(obj, "hopital", None), "type_hopital", None)

    def get_id_etablissement_hopital_rattachement(self, obj):
        pharmacie = getattr(obj, "pharmacie", None)
        return pharmacie.id_etablissement_hopital_rattachement_id if pharmacie else None


class AdministrateurInitialSerializer(serializers.Serializer):
    identifiant_connexion = serializers.CharField(max_length=30)
    email_professionnel = serializers.EmailField(max_length=70)
    nom = serializers.CharField(max_length=50)
    prenom = serializers.CharField(max_length=50)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    date_embauche = serializers.DateField()
    role_acces = serializers.CharField(max_length=20)

    def validate_password(self, value):
        validate_password(value)
        return value


class EtablissementProvisionSerializer(serializers.Serializer):
    nom_etablissement = serializers.CharField(max_length=80)
    type_etablissement = serializers.ChoiceField(choices=Etablissement.TYPE_CHOICES)
    adresse = serializers.CharField(max_length=150)
    telephone_contact = serializers.CharField(max_length=20)
    email_contact = serializers.EmailField(max_length=70, required=False, allow_null=True, allow_blank=True)
    numero_agrement = serializers.CharField(max_length=30, required=False)
    type_hopital = serializers.CharField(max_length=30, required=False, allow_blank=True, allow_null=True)
    numero_agrement_pharmaceutique = serializers.CharField(max_length=30, required=False)
    id_etablissement_hopital_rattachement = serializers.UUIDField(required=False, allow_null=True)
    administrateur_initial = AdministrateurInitialSerializer()

    def validate(self, attrs):
        if attrs["type_etablissement"] == Etablissement.TYPE_HOPITAL and not attrs.get("numero_agrement"):
            raise serializers.ValidationError({"numero_agrement": "Le numéro d'agrément est requis pour un hôpital."})
        if attrs["type_etablissement"] == Etablissement.TYPE_PHARMACIE and not attrs.get("numero_agrement_pharmaceutique"):
            raise serializers.ValidationError({"numero_agrement_pharmaceutique": "Le numéro d'agrément est requis pour une pharmacie."})
        if attrs["type_etablissement"] == Etablissement.TYPE_PHARMACIE:
            id_hopital = attrs.get("id_etablissement_hopital_rattachement")
            if id_hopital and not Hopital.objects.filter(pk=id_hopital).exists():
                raise serializers.ValidationError({"id_etablissement_hopital_rattachement": "L'hôpital de rattachement est introuvable."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        values = dict(validated_data)
        admin_data = values.pop("administrateur_initial")
        hopital_fields = {key: values.pop(key, None) for key in ("numero_agrement", "type_hopital")}
        pharmacie_fields = {
            key: values.pop(key, None)
            for key in ("numero_agrement_pharmaceutique", "id_etablissement_hopital_rattachement")
        }
        etablissement = Etablissement.objects.create(**values)
        if etablissement.type_etablissement == Etablissement.TYPE_HOPITAL:
            Hopital.objects.create(
                id_etablissement=etablissement,
                numero_agrement=hopital_fields["numero_agrement"],
                type_hopital=hopital_fields["type_hopital"],
            )
        else:
            Pharmacie.objects.create(
                id_etablissement=etablissement,
                numero_agrement_pharmaceutique=pharmacie_fields["numero_agrement_pharmaceutique"],
                id_etablissement_hopital_rattachement_id=pharmacie_fields["id_etablissement_hopital_rattachement"],
            )
        Personnel.objects.create_user(
            password=admin_data["password"],
            id_etablissement=etablissement,
            role_metier="administrateur",
            **{key: admin_data[key] for key in ("identifiant_connexion", "email_professionnel", "nom", "prenom", "date_embauche", "role_acces")},
        )
        return etablissement


class PersonnelSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    specialite = serializers.CharField(max_length=40, write_only=True, required=False)
    matricule_superviseur = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    specialite_medecin = serializers.SerializerMethodField()
    photo_profil = serializers.ImageField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = Personnel
        fields = (
            "matricule_personnel", "nom", "prenom", "email_professionnel", "role_metier",
            "date_embauche", "identifiant_connexion", "role_acces", "actif", "password",
            "specialite", "matricule_superviseur", "specialite_medecin",
            "photo_profil",
        )
        read_only_fields = ("matricule_personnel", "actif", "specialite_medecin")

    def get_specialite_medecin(self, obj):
        try:
            return obj.medecin.specialite
        except Medecin.DoesNotExist:
            return None

    def validate_password(self, value):
        validate_password(value, user=self.instance)
        return value

    def validate(self, attrs):
        role = attrs.get("role_metier", getattr(self.instance, "role_metier", None))
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Le mot de passe est obligatoire à la création."})
        if role == "medecin" and not (attrs.get("specialite") or self.instance and self.get_specialite_medecin(self.instance)):
            raise serializers.ValidationError({"specialite": "La spécialité est obligatoire pour un médecin."})
        if self.instance and role != self.instance.role_metier:
            raise serializers.ValidationError({"role_metier": "Le rôle métier ne peut pas être modifié par cette API."})
        if role != "medecin" and (
            attrs.get("specialite") or attrs.get("matricule_superviseur") or attrs.get("photo_profil")
        ):
            raise serializers.ValidationError({"specialite": "Les champs médecin ne sont acceptés que pour un médecin."})
        superviseur = attrs.get("matricule_superviseur")
        if superviseur:
            existe = Personnel.objects.filter(
                pk=superviseur,
                id_etablissement_id=self.context["request"].user.id_etablissement_id,
                role_metier="medecin",
            ).exists()
            if not existe:
                raise serializers.ValidationError({"matricule_superviseur": "Le superviseur doit être un médecin de cet établissement."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        specialite = validated_data.pop("specialite", None)
        superviseur = validated_data.pop("matricule_superviseur", None)
        photo_profil = validated_data.pop("photo_profil", None)
        etablissement = self.context["request"].user.id_etablissement
        personnel = Personnel.objects.create_user(
            password=password,
            id_etablissement=etablissement,
            **validated_data,
        )
        if personnel.role_metier == "medecin":
            Medecin.objects.create(
                matricule_personnel=personnel,
                specialite=specialite,
                matricule_superviseur_id=superviseur,
                photo_profil=photo_profil,
            )
        return personnel

    @transaction.atomic
    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        specialite = validated_data.pop("specialite", None)
        superviseur = validated_data.pop("matricule_superviseur", serializers.empty)
        photo_profil = validated_data.pop("photo_profil", serializers.empty)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        if instance.role_metier == "medecin":
            Medecin.objects.update_or_create(
                matricule_personnel=instance,
                defaults={
                    **({"specialite": specialite} if specialite is not None else {}),
                    **({"matricule_superviseur_id": superviseur} if superviseur is not serializers.empty else {}),
                    **({"photo_profil": photo_profil} if photo_profil is not serializers.empty else {}),
                },
            )
        return instance


class MedecinSerializer(serializers.ModelSerializer):
    nom = serializers.CharField(source="matricule_personnel.nom", read_only=True)
    prenom = serializers.CharField(source="matricule_personnel.prenom", read_only=True)
    id_etablissement = serializers.UUIDField(source="matricule_personnel.id_etablissement_id", read_only=True)
    photo_profil = serializers.ImageField(read_only=True)

    class Meta:
        model = Medecin
        fields = ("matricule_personnel", "nom", "prenom", "id_etablissement", "specialite", "photo_profil", "matricule_superviseur")
        read_only_fields = fields


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ("code_service", "nom_service", "matricule_chef_service")
        read_only_fields = ("code_service",)

    def validate_matricule_chef_service(self, medecin):
        if medecin and medecin.matricule_personnel.id_etablissement_id != self.context["request"].user.id_etablissement_id:
            raise serializers.ValidationError("Le chef de service doit appartenir à cet établissement.")
        return medecin


class AffectationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Affectation
        fields = (
            "id_affectation", "matricule_personnel", "code_service",
            "date_debut_affectation", "date_fin_affectation",
        )
        read_only_fields = ("id_affectation",)

    def validate(self, attrs):
        etablissement_id = self.context["request"].user.id_etablissement_id
        personnel = attrs.get("matricule_personnel", getattr(self.instance, "matricule_personnel", None))
        service = attrs.get("code_service", getattr(self.instance, "code_service", None))
        if personnel and personnel.id_etablissement_id != etablissement_id:
            raise serializers.ValidationError({"matricule_personnel": "Le personnel doit appartenir à cet établissement."})
        if service and service.id_etablissement_id != etablissement_id:
            raise serializers.ValidationError({"code_service": "Le service doit appartenir à cet établissement."})
        return attrs
