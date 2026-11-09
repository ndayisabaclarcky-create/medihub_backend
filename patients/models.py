"""
Bloc 2 du dictionnaire de données — Patients, clients, téléphones,
assurances, partage de dossier, index de rapprochement.
"""

from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import check_password, make_password
from django.db import models, transaction
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Etablissement, Medecin, Personnel


def _verifier_type_etablissement(instance, type_attendu, message):
    """
    Vérifie le type de l'établissement porteur. Ne fait rien si id_etablissement
    est vide : full_clean() signale déjà ce champ obligatoire, et l'accès à
    instance.id_etablissement lèverait sinon RelatedObjectDoesNotExist (erreur 500).
    """
    if instance.id_etablissement_id is None:
        return
    if instance.id_etablissement.type_etablissement != type_attendu:
        raise ValidationError(message)


class ComptePatient(models.Model):
    """Compte MediHub global ; les dossiers cliniques restent propres aux hôpitaux."""

    SEXE_CHOICES = [("M", "Masculin"), ("F", "Féminin")]

    id_compte_patient = uuid_pk_field()
    identifiant_connexion = models.CharField(max_length=50, unique=True)
    nom = models.CharField(max_length=50)
    prenom = models.CharField(max_length=50)
    date_naissance = models.DateField()
    sexe = models.CharField(max_length=1, choices=SEXE_CHOICES)
    numero_telephone = models.CharField(max_length=20, unique=True)
    mot_de_passe = models.CharField(max_length=128)
    telephone_verifie = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    # Informations déclarées par le patient, conservées distinctement des dossiers cliniques vérifiés.
    allergies_declarees = models.CharField(max_length=500, blank=True)
    antecedents_declares = models.CharField(max_length=1000, blank=True)
    groupe_sanguin_declare = models.CharField(max_length=3, blank=True, null=True)

    class Meta:
        db_table = "compte_patient"
        verbose_name = "Compte patient MediHub"
        verbose_name_plural = "Comptes patients MediHub"

    def set_password(self, raw_password):
        self.mot_de_passe = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.mot_de_passe)

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.identifiant_connexion})"


class CodeComptePatient(models.Model):
    """OTP à usage unique pour activer un compte ou confirmer une connexion."""

    INSCRIPTION = "inscription"
    CONNEXION = "connexion"
    USAGE_CHOICES = [(INSCRIPTION, "Activation"), (CONNEXION, "Connexion")]

    id_code = uuid_pk_field()
    id_compte_patient = models.ForeignKey(
        ComptePatient, on_delete=models.CASCADE, related_name="codes_verification"
    )
    usage = models.CharField(max_length=15, choices=USAGE_CHOICES)
    code_hash = models.CharField(max_length=128)
    date_generation = models.DateTimeField(default=timezone.now)
    date_expiration = models.DateTimeField()
    tentatives = models.PositiveSmallIntegerField(default=0)
    utilise = models.BooleanField(default=False)

    class Meta:
        db_table = "code_compte_patient"
        ordering = ("-date_generation",)

    def verifier(self, code):
        return check_password(code, self.code_hash)

    def __str__(self):
        return f"Code {self.usage} pour {self.id_compte_patient_id}"


class Client(ValidateOnSaveMixin, EtablissementScopedModel):
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
        _verifier_type_etablissement(
            self, Etablissement.TYPE_PHARMACIE, "Un client ne peut être enregistré que dans une pharmacie."
        )


class Patient(ValidateOnSaveMixin, EtablissementScopedModel):
    """
    Identifiant : id_patient — artificiel (UUID).
    Reste propre à un seul hôpital (dossier non partagé).
    """

    SEXE_CHOICES = [("M", "Masculin"), ("F", "Féminin")]
    GROUPE_SANGUIN_CHOICES = [
        ("A+", "A+"), ("A-", "A-"), ("B+", "B+"), ("B-", "B-"),
        ("AB+", "AB+"), ("AB-", "AB-"), ("O+", "O+"), ("O-", "O-"),
    ]

    id_patient = uuid_pk_field()
    compte_patient = models.ForeignKey(
        ComptePatient,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="dossiers_hospitaliers",
    )
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
    groupe_sanguin = models.CharField(max_length=3, choices=GROUPE_SANGUIN_CHOICES, blank=True, null=True)
    medecin_referent = models.ForeignKey(
        "etablissements.Medecin",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        db_column="matricule_medecin_referent",
        related_name="patients_referents",
    )
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
        _verifier_type_etablissement(
            self, Etablissement.TYPE_HOPITAL, "Un patient ne peut être enregistré que dans un hôpital."
        )
        if self.medecin_referent_id and self.id_etablissement_id:
            medecin_du_meme_hopital = Medecin.objects.filter(
                pk=self.medecin_referent_id,
                matricule_personnel__id_etablissement_id=self.id_etablissement_id,
            ).exists()
            if not medecin_du_meme_hopital:
                raise ValidationError("Le médecin référent doit appartenir au même hôpital que le patient.")

    def save(self, *args, **kwargs):
        """
        RG35-RG37 : alimente automatiquement INDEX_RAPPROCHEMENT à la
        création ET à la mise à jour du patient.

        Les deux écritures (patient puis index) sont dans une même transaction :
        si la seconde échoue, le patient n'est pas créé — jamais de patient
        sans entrée d'index.
        """
        with transaction.atomic():
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


class MesurePoids(ValidateOnSaveMixin, EtablissementScopedModel):
    """Mesure de poids datée, conservée pour suivre l'évolution du patient."""

    id_mesure_poids = uuid_pk_field()
    poids_kg = models.DecimalField(max_digits=5, decimal_places=2)
    date_mesure = models.DateTimeField(auto_now_add=True)
    id_patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        db_column="id_patient",
        related_name="mesures_poids",
    )
    matricule_personnel = models.ForeignKey(
        "etablissements.Personnel",
        on_delete=models.PROTECT,
        db_column="matricule_personnel",
        related_name="mesures_poids_enregistrees",
    )

    class Meta:
        db_table = "mesure_poids_patient"
        verbose_name = "Mesure du poids patient"
        verbose_name_plural = "Mesures du poids patient"
        ordering = ("-date_mesure",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(poids_kg__gt=0, poids_kg__lte=500),
                name="chk_mesure_poids_0_500",
            ),
        ]

    def clean(self):
        if self.id_patient_id and not Patient.objects.filter(
            pk=self.id_patient_id, id_etablissement_id=self.id_etablissement_id
        ).exists():
            raise ValidationError("La mesure doit appartenir au même hôpital que le patient.")
        if self.matricule_personnel_id and not Personnel.objects.filter(
            pk=self.matricule_personnel_id, id_etablissement_id=self.id_etablissement_id
        ).exists():
            raise ValidationError("Le professionnel doit appartenir au même hôpital que la mesure.")


class HistoriqueMedicalPartage(ValidateOnSaveMixin, EtablissementScopedModel):
    """Instantané consenti d'un résumé médical reçu par un hôpital."""

    id_historique_partage = uuid_pk_field()
    id_compte_patient = models.ForeignKey(
        ComptePatient, on_delete=models.PROTECT, related_name="historiques_partages"
    )
    id_patient_source = models.UUIDField()
    id_etablissement_source = models.UUIDField()
    id_patient_destination = models.ForeignKey(
        Patient, on_delete=models.PROTECT, db_column="id_patient_destination",
        related_name="historiques_medicaux_recus",
    )
    resume_medical = models.JSONField(default=dict)
    date_consentement = models.DateTimeField(auto_now_add=True)
    version_consentement = models.CharField(max_length=20, default="v1")

    class Meta:
        db_table = "historique_medical_partage"
        ordering = ("-date_consentement",)

    def clean(self):
        if self.id_patient_destination_id and self.id_etablissement_id:
            if not Patient.objects.filter(
                pk=self.id_patient_destination_id,
                id_etablissement_id=self.id_etablissement_id,
                compte_patient_id=self.id_compte_patient_id,
            ).exists():
                raise ValidationError("Le dossier destinataire doit être lié au compte patient connecté.")
        if self.id_etablissement_source == self.id_etablissement_id:
            raise ValidationError("Le partage doit provenir d'un autre hôpital.")


class DocumentMedicalPartage(ValidateOnSaveMixin, EtablissementScopedModel):
    """Copie PDF figée d'un document sélectionné par le patient."""

    id_document_partage = uuid_pk_field()
    historique = models.ForeignKey(
        HistoriqueMedicalPartage, on_delete=models.CASCADE, related_name="documents"
    )
    type_document_source = models.CharField(max_length=20)
    id_document_source = models.UUIDField()
    titre = models.CharField(max_length=150)
    date_document = models.DateField(blank=True, null=True)
    contenu_pdf = models.BinaryField()

    class Meta:
        db_table = "document_medical_partage"

    def clean(self):
        if self.historique_id and self.id_etablissement_id != self.historique.id_etablissement_id:
            raise ValidationError("Le document partagé et son historique doivent appartenir au même hôpital.")


class Telephone(ValidateOnSaveMixin, EtablissementScopedModel):
    """
    Donnée multivaluée du Patient (mise en 1FN). Identifiant de
    substitution : id_telephone — UUID.

    Écart volontaire au dictionnaire de données v1.1 (inscrit en v1.2) :
    id_etablissement n'y était pas listé (déductible via id_patient), mais on
    le garde en direct pour pouvoir lui appliquer la même policy RLS qu'à
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

    def clean(self):
        # id_etablissement est dupliqué par rapport au patient : les deux
        # doivent rester identiques.
        if self.id_etablissement_id is None or self.id_patient_id is None:
            return
        if self.id_patient.id_etablissement_id != self.id_etablissement_id:
            raise ValidationError("Le téléphone doit appartenir au même établissement que son patient.")


class Assurance(ValidateOnSaveMixin, EtablissementScopedModel):
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
            ),
            models.CheckConstraint(
                condition=models.Q(taux_prise_en_charge__gte=0, taux_prise_en_charge__lte=100),
                name="chk_assurance_taux_0_100",
                violation_error_message="Le taux de prise en charge doit être compris entre 0 et 100.",
            ),
        ]

    def __str__(self):
        return f"{self.nom_assureur} — police {self.numero_police}"

    def clean(self):
        # Le taux 0-100 est garanti par la CheckConstraint (vérifiée par full_clean
        # et par la base) ; il n'est plus testé ici.
        _verifier_type_etablissement(
            self, Etablissement.TYPE_HOPITAL, "Une assurance ne peut être enregistrée que dans un hôpital."
        )


class PartageDossier(models.Model):
    """
    Identifiant : id_partage — artificiel (UUID). RG35 à RG37.
    Exception encadrée à l'isolation multi-tenant : le partage relie deux
    patients d'établissements DIFFÉRENTS — c'est pourquoi ce modèle
    n'hérite PAS de EtablissementScopedModel (il est intrinsèquement
    inter-établissements). Hors RLS : le filtrage par établissement
    concerné devra être fait explicitement dans les vues/serializers.
    (Exception validée et consignée avec Personnel et Établissement — voir
    MediHub_Modele_Donnees_Technique_v1.2, section « Isolation RLS ».)

    Preuve de consentement (RG37) : les clés vers Patient sont en PROTECT —
    on ne peut pas supprimer un patient impliqué dans un partage, ce qui
    effacerait la trace du consentement. Un même patient destinataire ne peut
    recevoir qu'un seul partage (RG36 « une seule fois »), garanti en base.

    Création : uniquement via patients.services.partager_dossier().
    """

    id_partage = uuid_pk_field()
    date_partage = models.DateTimeField(auto_now_add=True)
    id_patient_source = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        db_column="id_patient_source",
        related_name="partages_issus",
    )
    id_patient_destination = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
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
        constraints = [
            models.UniqueConstraint(
                fields=["id_patient_destination"],
                name="uniq_partage_patient_destination",
                violation_error_message="Ce dossier a déjà reçu un partage (RG36 : une seule fois).",
            ),
            models.CheckConstraint(
                condition=~models.Q(id_patient_source=models.F("id_patient_destination")),
                name="chk_partage_source_ne_destination",
            ),
        ]

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
