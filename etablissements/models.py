"""
Bloc 1 du dictionnaire de données — Établissements, personnel, comptes, journalisation.
"""

import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import FileExtensionValidator

from core.models import EtablissementScopedModel, uuid_pk_field
from etablissements.managers import PersonnelManager


def valider_taille_photo_medecin(fichier):
    if fichier.size > 3 * 1024 * 1024:
        raise ValidationError("La photo du médecin ne peut pas dépasser 3 Mo.")


class Etablissement(models.Model):
    """Sur-type : tout établissement est soit un hôpital, soit une pharmacie."""

    TYPE_HOPITAL = "hopital"
    TYPE_PHARMACIE = "pharmacie"
    TYPE_CHOICES = [
        (TYPE_HOPITAL, "Hôpital"),
        (TYPE_PHARMACIE, "Pharmacie"),
    ]

    id_etablissement = uuid_pk_field()
    nom_etablissement = models.CharField(max_length=80)
    type_etablissement = models.CharField(max_length=20, choices=TYPE_CHOICES)
    adresse = models.CharField(max_length=150)
    telephone_contact = models.CharField(max_length=20)
    email_contact = models.EmailField(max_length=70, blank=True, null=True)
    date_creation_compte = models.DateField(auto_now_add=True)

    class Meta:
        db_table = "etablissement"
        verbose_name = "Établissement"
        verbose_name_plural = "Établissements"

    def __str__(self):
        return self.nom_etablissement


class Hopital(models.Model):
    """Sous-type d'Établissement, identifiant hérité."""

    id_etablissement = models.OneToOneField(
        Etablissement,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="id_etablissement",
        related_name="hopital",
    )
    numero_agrement = models.CharField(max_length=30)
    type_hopital = models.CharField(max_length=30, blank=True, null=True)

    class Meta:
        db_table = "hopital"
        verbose_name = "Hôpital"
        verbose_name_plural = "Hôpitaux"

    def __str__(self):
        return self.id_etablissement.nom_etablissement

    def clean(self):
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("type_etablissement doit être 'hopital' pour une ligne Hôpital.")


class Pharmacie(models.Model):
    """Sous-type d'Établissement, identifiant hérité."""

    id_etablissement = models.OneToOneField(
        Etablissement,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="id_etablissement",
        related_name="pharmacie",
    )
    numero_agrement_pharmaceutique = models.CharField(max_length=30)
    id_etablissement_hopital_rattachement = models.ForeignKey(
        Hopital,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        db_column="id_etablissement_hopital_rattachement",
        related_name="pharmacies_rattachees",
        help_text="NULL = pharmacie indépendante (RG33).",
    )

    class Meta:
        db_table = "pharmacie"
        verbose_name = "Pharmacie"
        verbose_name_plural = "Pharmacies"

    def __str__(self):
        return self.id_etablissement.nom_etablissement

    def clean(self):
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_PHARMACIE:
            raise ValidationError("type_etablissement doit être 'pharmacie' pour une ligne Pharmacie.")

class Personnel(AbstractBaseUser, PermissionsMixin, EtablissementScopedModel):
    """
    Identifiant : matricule_personnel — artificiel (UUID).
    Inclut l'ancien Compte_utilisateur (RG28) et sert de AUTH_USER_MODEL.
    Hors Row-Level Security (voir README) : la connexion doit pouvoir
    retrouver une ligne PERSONNEL par identifiant_connexion avant même
    de connaître son établissement.
    """

    ROLE_METIER_CHOICES = [
        ("medecin", "Médecin"),
        ("infirmier", "Infirmier"),
        ("secretaire", "Secrétaire"),
        ("pharmacien", "Pharmacien"),
        ("comptable", "Comptable"),
        ("technicien_labo", "Technicien de laboratoire"),
        ("administrateur", "Administrateur"),
    ]

    matricule_personnel = uuid_pk_field()
    nom = models.CharField(max_length=50)
    prenom = models.CharField(max_length=50)
    email_professionnel = models.EmailField(max_length=70, unique=True)
    role_metier = models.CharField(max_length=20, choices=ROLE_METIER_CHOICES)
    date_embauche = models.DateField()
    identifiant_connexion = models.CharField(max_length=30, unique=True)
    role_acces = models.CharField(
        max_length=20,
        help_text="Niveau de permission système, distinct du rôle métier.",
    )
    actif = models.BooleanField(default=True)
    # id_etablissement : hérité de EtablissementScopedModel.

    is_staff = models.BooleanField(
        default=False,
        help_text="Autorise l'accès à l'interface d'administration Django.",
    )
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = PersonnelManager()

    USERNAME_FIELD = "identifiant_connexion"
    REQUIRED_FIELDS = [
        "email_professionnel",
        "nom",
        "prenom",
        "role_metier",
        "date_embauche",
        "role_acces",
        "id_etablissement",
    ]

    class Meta:
        db_table = "personnel"
        verbose_name = "Personnel"
        verbose_name_plural = "Personnel"
        swappable = "AUTH_USER_MODEL"

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.identifiant_connexion})"

    @property
    def is_active(self):
        return self.actif

    @is_active.setter
    def is_active(self, value):
        self.actif = value

class Medecin(models.Model):
    """Spécialisation de Personnel."""

    matricule_personnel = models.OneToOneField(
        Personnel,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="matricule_personnel",
        related_name="medecin",
    )
    specialite = models.CharField(max_length=40)
    photo_profil = models.ImageField(
        upload_to="medecins/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(("jpg", "jpeg", "png", "webp")), valider_taille_photo_medecin],
    )
    matricule_superviseur = models.ForeignKey(
        Personnel,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        db_column="matricule_superviseur",
        related_name="medecins_supervises",
        help_text="Association SUPERVISER (réflexive).",
    )

    class Meta:
        db_table = "medecin"
        verbose_name = "Médecin"
        verbose_name_plural = "Médecins"

    def __str__(self):
        return str(self.matricule_personnel)


class Service(EtablissementScopedModel):
    """Identifiant : code_service — artificiel (UUID). N'existe que côté hôpital."""

    code_service = uuid_pk_field()
    nom_service = models.CharField(max_length=30)
    matricule_chef_service = models.ForeignKey(
        Medecin,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        db_column="matricule_chef_service",
        related_name="services_diriges",
        help_text="Association DIRIGER.",
    )

    class Meta:
        db_table = "service"
        verbose_name = "Service"
        verbose_name_plural = "Services"

    def __str__(self):
        return self.nom_service

    def clean(self):
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Un service ne peut appartenir qu'à un établissement de type hôpital.")


class Affectation(EtablissementScopedModel):
    """Association porteuse historisée ; identifiant de substitution : id_affectation — UUID."""

    id_affectation = uuid_pk_field()
    matricule_personnel = models.ForeignKey(
        Personnel,
        on_delete=models.CASCADE,
        db_column="matricule_personnel",
        related_name="affectations",
    )
    code_service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        db_column="code_service",
        related_name="affectations",
    )
    date_debut_affectation = models.DateField()
    date_fin_affectation = models.DateField(blank=True, null=True)

    class Meta:
        db_table = "affectation"
        verbose_name = "Affectation"
        verbose_name_plural = "Affectations"
        constraints = [
            models.UniqueConstraint(
                fields=["matricule_personnel", "code_service", "date_debut_affectation"],
                name="uniq_affectation_personnel_service_debut",
            )
        ]

    def __str__(self):
        return f"{self.matricule_personnel} → {self.code_service} ({self.date_debut_affectation})"


class JournalAction(EtablissementScopedModel):
    """Identifiant : id_journal — artificiel (UUID)."""

    id_journal = uuid_pk_field()
    date_heure_action = models.DateTimeField(auto_now_add=True)
    type_action = models.CharField(max_length=30)
    details = models.CharField(max_length=300, blank=True, null=True)
    matricule_personnel = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        db_column="matricule_personnel",
        related_name="actions_journalisees",
    )

    class Meta:
        db_table = "journal_action"
        verbose_name = "Action journalisée"
        verbose_name_plural = "Journal des actions"
        ordering = ["-date_heure_action"]

    def __str__(self):
        return f"{self.type_action} — {self.date_heure_action:%Y-%m-%d %H:%M}"
