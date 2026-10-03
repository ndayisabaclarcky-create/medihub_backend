"""
Bloc 2 du dictionnaire de données — Patients, clients, téléphones,
assurances, partage de dossier, index de rapprochement.
"""

from django.core.exceptions import ValidationError
from django.db import models

from core.models import EtablissementScopedModel, uuid_pk_field
from etablissements.models import Etablissement


class Client(EtablissementScopedModel):
    """
    Identifiant : id_client — artificiel (UUID).
    Fiche volontairement légère (RG31) : pas de table Téléphone dédiée
    pour Client, contrairement à Patient.
    """

    id_client = uuid_pk_field()
    nom = models.CharField(max_length=50)
    prenom = models.CharField(max_length=50, blank=True, null=True)
    telephone_contact = models.CharField(max_length=20, blank=True, null=True)
    # id_etablissement : hérité de EtablissementScopedModel (ENREGISTRER_CLIENT).

    class Meta:
        db_table = "client"
        verbose_name = "Client"
        verbose_name_plural = "Clients"

    def __str__(self):
        return f"{self.nom} {self.prenom}".strip()

    def clean(self):
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_PHARMACIE:
            raise ValidationError("Un client ne peut être enregistré que dans une pharmacie.")


class Patient(EtablissementScopedModel):
    """
    Identifiant : id_patient — artificiel (UUID).
    Reste propre à un seul hôpital (dossier non partagé).
    """

    SEXE_CHOICES = [("M", "Masculin"), ("F", "Féminin")]

    id_patient = uuid_pk_field()
    nom_patient = models.CharField(max_length=40)
    prenom_patient = models.CharField(max_length=40)
    date_naissance = models.DateField()
    sexe = models.CharField(max_length=1, choices=SEXE_CHOICES)
    adresse = models.CharField(max_length=100, blank=True, null=True)
    numero_piece_identite = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text="RG35 — utilisé pour le rapprochement uniquement.",
    )
    allergies = models.CharField(max_length=300, blank=True, null=True)
    antecedents_medicaux = models.CharField(max_length=300, blank=True, null=True)
    id_assurance = models.ForeignKey(
        "Assurance",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        db_column="id_assurance",
        related_name="patients_assures",
        help_text="Association ASSURER.",
    )
    # id_etablissement : hérité (ENREGISTRER_PATIENT).

    class Meta:
        db_table = "patient"
        verbose_name = "Patient"
        verbose_name_plural = "Patients"

    def __str__(self):
        return f"{self.nom_patient} {self.prenom_patient}"

    def clean(self):
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Un patient ne peut être enregistré que dans un hôpital.")

    def save(self, *args, **kwargs):
        """
        RG35-RG37 : alimente automatiquement INDEX_RAPPROCHEMENT à la
        création ET à la mise à jour du patient.
        """
        super().save(*args, **kwargs)
        numero = self.numero_piece_identite
        if numero:
            IndexRapprochement.objects.update_or_create(
                id_patient=self,
                defaults={
                    "numero_piece_identite": numero,
                    "id_etablissement": self.id_etablissement,
                },
            )
        else:
            IndexRapprochement.objects.filter(id_patient=self).delete()


class Telephone(EtablissementScopedModel):
    """
    Donnée multivaluée du Patient (mise en 1FN). Identifiant de
    substitution : id_telephone — UUID.

    Écart volontaire au dictionnaire de données : id_etablissement n'y est
    pas listé pour cette table (déductible via id_patient), mais on le
    garde en direct pour pouvoir lui appliquer la même policy RLS qu'à
    Patient — un numéro de téléphone reste une donnée personnelle sensible.
    """

    id_telephone = uuid_pk_field()
    numero_telephone = models.CharField(max_length=20)
    type_telephone = models.CharField(max_length=15)
    id_patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        db_column="id_patient",
        related_name="telephones",
    )

    class Meta:
        db_table = "telephone"
        verbose_name = "Téléphone"
        verbose_name_plural = "Téléphones"
        constraints = [
            models.UniqueConstraint(
                fields=["id_patient", "numero_telephone"],
                name="uniq_telephone_patient_numero",
            )
        ]

    def __str__(self):
        return f"{self.numero_telephone} ({self.type_telephone})"


class Assurance(EtablissementScopedModel):
    """
    Identifiant : id_assurance — artificiel (UUID).
    Propre à chaque hôpital (taux négociés séparément).
    """

    id_assurance = uuid_pk_field()
    numero_police = models.CharField(max_length=30)
    nom_assureur = models.CharField(max_length=40)
    taux_prise_en_charge = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = "assurance"
        verbose_name = "Assurance"
        verbose_name_plural = "Assurances"
        constraints = [
            models.UniqueConstraint(
                fields=["numero_police", "id_etablissement"],
                name="uniq_assurance_police_etablissement",
            )
        ]

    def __str__(self):
        return f"{self.nom_assureur} — police {self.numero_police}"

    def clean(self):
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Une assurance ne peut être enregistrée que dans un hôpital.")
        if not (0 <= self.taux_prise_en_charge <= 100):
            raise ValidationError("Le taux de prise en charge doit être compris entre 0 et 100.")


class PartageDossier(models.Model):
    """
    Identifiant : id_partage — artificiel (UUID). RG35 à RG37.
    Exception encadrée à l'isolation multi-tenant : le partage relie deux
    patients d'établissements DIFFÉRENTS — c'est pourquoi ce modèle
    n'hérite PAS de EtablissementScopedModel (il est intrinsèquement
    inter-établissements). Hors RLS : le filtrage par établissement
    concerné devra être fait explicitement dans les vues/serializers.
    """

    id_partage = uuid_pk_field()
    date_partage = models.DateTimeField(auto_now_add=True)
    id_patient_source = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        db_column="id_patient_source",
        related_name="partages_issus",
    )
    id_patient_destination = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        db_column="id_patient_destination",
        related_name="partages_recus",
    )
    matricule_personnel = models.ForeignKey(
        "etablissements.Personnel",
        on_delete=models.PROTECT,
        db_column="matricule_personnel",
        related_name="partages_recueillis",
        help_text="A recueilli le consentement.",
    )

    class Meta:
        db_table = "partage_dossier"
        verbose_name = "Partage de dossier"
        verbose_name_plural = "Partages de dossier"

    def __str__(self):
        return f"Partage {self.id_patient_source_id} → {self.id_patient_destination_id}"

    def clean(self):
        if self.id_patient_source_id == self.id_patient_destination_id:
            raise ValidationError("Un dossier ne peut pas être partagé avec lui-même.")


class IndexRapprochement(EtablissementScopedModel):
    """
    Table technique minimale : détecte qu'un patient est déjà connu
    ailleurs, SANS exposer de donnée médicale avant consentement (RG35).
    Alimentée automatiquement par Patient.save().
    """

    id_index = uuid_pk_field()
    numero_piece_identite = models.CharField(
        max_length=30,
        db_index=True,
        help_text="Indexé — critère de recherche du rapprochement.",
    )
    id_patient = models.OneToOneField(
        Patient,
        on_delete=models.CASCADE,
        db_column="id_patient",
        related_name="entree_rapprochement",
    )

    class Meta:
        db_table = "index_rapprochement"
        verbose_name = "Entrée d'index de rapprochement"
        verbose_name_plural = "Index de rapprochement"

    def __str__(self):
        return f"{self.numero_piece_identite} → patient {self.id_patient_id}"
