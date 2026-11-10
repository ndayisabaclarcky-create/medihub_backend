"""
Bloc 3 du dictionnaire de données — Rendez-vous, actes, consultations,
hospitalisations, chambres et lits.

Conventions reprises des Blocs 1 et 2 :
- chaque table porte id_etablissement (EtablissementScopedModel) pour la RLS ;
- ValidateOnSaveMixin fait tourner full_clean() à chaque save() ;
- les sous-types d'Acte suivent le modèle Hopital/Pharmacie : une
  OneToOneField qui sert de clé primaire (pas d'héritage multi-tables Django).
"""

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Medecin, Service
from patients.models import Patient


def _etablissement_de(modele, pk):
    """
    Retourne l'id_etablissement de la ligne `pk` de `modele`, ou None si elle
    n'existe pas OU si la RLS la rend invisible. Dans les deux cas c'est
    ForeignKey.validate() (étape clean_fields) qui signale déjà l'erreur : les
    clean() ci-dessous ignorent donc simplement ce cas au lieu de planter.
    """
    if pk is None:
        return None
    return modele.objects.filter(pk=pk).values_list("id_etablissement_id", flat=True).first()


def _etablissement_du_medecin(matricule):
    """Un médecin n'a pas d'id_etablissement : on le lit sur son Personnel."""
    if matricule is None:
        return None
    return (
        Medecin.objects.filter(pk=matricule)
        .values_list("matricule_personnel__id_etablissement_id", flat=True)
        .first()
    )


class RendezVous(ValidateOnSaveMixin, EtablissementScopedModel):
    """Identifiant : id_rdv — artificiel (UUID)."""

    PLANIFIE = "planifie"
    HONORE = "honore"
    ANNULE = "annule"
    ABSENT = "absent"
    STATUT_CHOICES = [
        (PLANIFIE, "Planifié"),
        (HONORE, "Honoré"),
        (ANNULE, "Annulé"),
        (ABSENT, "Absent"),
    ]

    id_rdv = uuid_pk_field()
    date_rendez_vous = models.DateField()
    heure_rendez_vous = models.TimeField()
    motif = models.CharField(max_length=200, blank=True)
    statut_rendez_vous = models.CharField(max_length=10, choices=STATUT_CHOICES, default=PLANIFIE)
    id_patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        db_column="id_patient",
        related_name="rendez_vous",
    )
    matricule_personnel = models.ForeignKey(
        Medecin,
        on_delete=models.PROTECT,
        db_column="matricule_personnel",
        related_name="rendez_vous",
    )
    # id_etablissement : hérité de EtablissementScopedModel.

    class Meta:
        db_table = "rendez_vous"
        verbose_name = "Rendez-vous"
        verbose_name_plural = "Rendez-vous"
        constraints = [
            # RG05 : un médecin n'a qu'un rendez-vous par créneau. Un rendez-vous
            # annulé libère le créneau (sinon il resterait bloqué pour toujours).
            models.UniqueConstraint(
                fields=["matricule_personnel", "date_rendez_vous", "heure_rendez_vous"],
                condition=~models.Q(statut_rendez_vous="annule"),
                name="uniq_rdv_medecin_creneau_actif",
                violation_error_message="Ce médecin a déjà un rendez-vous sur ce créneau (RG05).",
            ),
            models.CheckConstraint(
                condition=models.Q(statut_rendez_vous__in=["planifie", "honore", "annule", "absent"]),
                name="chk_rdv_statut",
            ),
        ]

    def __str__(self):
        return f"RDV {self.date_rendez_vous} {self.heure_rendez_vous:%H:%M} — {self.id_patient_id}"

    def annuler(self, maintenant=None):
        """Annule le rendez-vous selon RG07.

        Une annulation faite moins de deux heures avant le créneau (ou après
        celui-ci) est enregistrée comme une absence. À exactement deux heures,
        elle reste une annulation normale.
        """
        if self.statut_rendez_vous != self.PLANIFIE:
            raise ValidationError("Seul un rendez-vous planifié peut être annulé.")

        fuseau = timezone.get_current_timezone()
        if maintenant is None:
            maintenant = timezone.localtime(timezone.now())
        elif timezone.is_naive(maintenant):
            maintenant = timezone.make_aware(maintenant, fuseau)
        else:
            maintenant = timezone.localtime(maintenant, fuseau)

        debut_rendez_vous = timezone.make_aware(
            datetime.combine(self.date_rendez_vous, self.heure_rendez_vous),
            fuseau,
        )
        delai = debut_rendez_vous - maintenant
        self.statut_rendez_vous = self.ABSENT if delai < timedelta(hours=2) else self.ANNULE
        self.save(update_fields=["statut_rendez_vous"])
        return self

    def clean(self):
        if self.id_etablissement_id is None:
            return
        etab_patient = _etablissement_de(Patient, self.id_patient_id)
        if etab_patient is not None and etab_patient != self.id_etablissement_id:
            raise ValidationError("Le patient doit appartenir au même établissement que le rendez-vous.")
        etab_medecin = _etablissement_du_medecin(self.matricule_personnel_id)
        if etab_medecin is not None and etab_medecin != self.id_etablissement_id:
            raise ValidationError("Le médecin doit appartenir au même établissement que le rendez-vous.")



class Acte(ValidateOnSaveMixin, EtablissementScopedModel):
    """
    Sur-type : Consultation, Hospitalisation (et plus tard Examen_prescrit) en
    sont les sous-types. Identifiant : id_acte — artificiel (UUID).
    """

    id_acte = uuid_pk_field()
    date_acte = models.DateField()
    libelle_acte = models.CharField(max_length=60)
    montant_base = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    id_patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        db_column="id_patient",
        related_name="actes",
    )

    class Meta:
        db_table = "acte"
        verbose_name = "Acte"
        verbose_name_plural = "Actes"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(montant_base__gte=0),
                name="chk_acte_montant_positif",
                violation_error_message="Le montant de base ne peut pas être négatif.",
            ),
        ]

    def __str__(self):
        return f"{self.libelle_acte} ({self.date_acte})"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        etab_patient = _etablissement_de(Patient, self.id_patient_id)
        if etab_patient is not None and etab_patient != self.id_etablissement_id:
            raise ValidationError("Le patient doit appartenir au même établissement que l'acte.")


class Consultation(ValidateOnSaveMixin, EtablissementScopedModel):
    """
    Sous-type d'Acte (identifiant hérité : id_acte). Peut exister sans rendez-vous
    (urgences, venues spontanées). Porte le statut d'épisode de soins (RG25).

    id_etablissement est recopié de l'acte pour que la RLS s'applique
    directement à cette table (même choix que Telephone au Bloc 2).
    """

    EN_COURS = "en_cours"
    CLOS = "clos"
    EPISODE_CHOICES = [(EN_COURS, "En cours"), (CLOS, "Clos")]

    id_acte = models.OneToOneField(
        Acte,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="id_acte",
        related_name="consultation",
    )
    diagnostic = models.CharField(max_length=200)
    observations = models.CharField(max_length=200, blank=True, null=True)
    id_rendez_vous = models.ForeignKey(
        RendezVous,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_rendez_vous",
        related_name="consultations",
        help_text="Vide pour les urgences et venues spontanées.",
    )
    matricule_personnel = models.ForeignKey(
        Medecin,
        on_delete=models.PROTECT,
        db_column="matricule_personnel",
        related_name="consultations_signees",
        help_text="Médecin qui signe le diagnostic.",
    )
    matricule_interne = models.ForeignKey(
        Medecin,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="matricule_interne",
        related_name="consultations_examinees",
        help_text="Interne supervisé (RG10).",
    )
    statut_episode = models.CharField(max_length=15, choices=EPISODE_CHOICES, default=EN_COURS)
    date_cloture_episode = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "consultation"
        verbose_name = "Consultation"
        verbose_name_plural = "Consultations"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(statut_episode__in=["en_cours", "clos"]),
                name="chk_consultation_statut_episode",
            ),
            # Un épisode clos a une date de clôture ; un épisode en cours n'en a pas.
            models.CheckConstraint(
                condition=(
                    models.Q(statut_episode="en_cours", date_cloture_episode__isnull=True)
                    | models.Q(statut_episode="clos", date_cloture_episode__isnull=False)
                ),
                name="chk_consultation_cloture_coherente",
                violation_error_message=(
                    "Un épisode clos doit avoir une date de clôture, un épisode en cours ne doit pas en avoir."
                ),
            ),
            models.CheckConstraint(
                condition=~models.Q(matricule_interne=models.F("matricule_personnel")),
                name="chk_consultation_interne_different_du_medecin",
                violation_error_message="L'interne ne peut pas être le médecin qui signe.",
            ),
        ]

    def __str__(self):
        return f"Consultation {self.id_acte_id} ({self.statut_episode})"

    def clean(self):
        if self.id_etablissement_id is None:
            return

        acte = Acte.objects.filter(pk=self.id_acte_id).values("id_etablissement_id", "id_patient_id").first()
        if acte and acte["id_etablissement_id"] != self.id_etablissement_id:
            raise ValidationError("La consultation doit appartenir au même établissement que son acte.")

        if self.id_rendez_vous_id:
            rdv = (
                RendezVous.objects.filter(pk=self.id_rendez_vous_id)
                .values("id_etablissement_id", "id_patient_id")
                .first()
            )
            if rdv and rdv["id_etablissement_id"] != self.id_etablissement_id:
                raise ValidationError("Le rendez-vous doit appartenir au même établissement que la consultation.")
            if rdv and acte and rdv["id_patient_id"] != acte["id_patient_id"]:
                raise ValidationError("Le rendez-vous et la consultation doivent concerner le même patient.")

        etab_medecin = _etablissement_du_medecin(self.matricule_personnel_id)
        if etab_medecin is not None and etab_medecin != self.id_etablissement_id:
            raise ValidationError("Le médecin doit appartenir au même établissement que la consultation.")

        if self.matricule_interne_id:
            if self.matricule_interne_id == self.matricule_personnel_id:
                raise ValidationError("L'interne ne peut pas être le médecin qui signe.")
            interne = (
                Medecin.objects.filter(pk=self.matricule_interne_id)
                .values("matricule_superviseur_id", "matricule_personnel__id_etablissement_id")
                .first()
            )
            if interne:
                if interne["matricule_personnel__id_etablissement_id"] != self.id_etablissement_id:
                    raise ValidationError("L'interne doit appartenir au même établissement que la consultation.")
                # RG10 : l'interne examine, son médecin superviseur valide et signe.
                if interne["matricule_superviseur_id"] != self.matricule_personnel_id:
                    raise ValidationError("Le médecin qui signe doit être le superviseur de l'interne (RG10).")

        if self.statut_episode == self.CLOS and self.date_cloture_episode is None:
            raise ValidationError("Un épisode clos doit avoir une date de clôture.")
        if self.statut_episode == self.EN_COURS and self.date_cloture_episode is not None:
            raise ValidationError("Un épisode en cours ne peut pas avoir de date de clôture.")



class Chambre(ValidateOnSaveMixin, EtablissementScopedModel):
    """Identifiant de substitution : id_chambre — UUID."""

    id_chambre = uuid_pk_field()
    numero_chambre = models.CharField(max_length=10)
    type_chambre = models.CharField(max_length=15, blank=True, null=True)
    code_service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        db_column="code_service",
        related_name="chambres",
        help_text="Association APPARTENIR.",
    )

    class Meta:
        db_table = "chambre"
        verbose_name = "Chambre"
        verbose_name_plural = "Chambres"
        constraints = [
            models.UniqueConstraint(
                fields=["numero_chambre", "id_etablissement"],
                name="uniq_chambre_numero_etablissement",
                violation_error_message="Ce numéro de chambre existe déjà dans cet établissement.",
            ),
        ]

    def __str__(self):
        return f"Chambre {self.numero_chambre}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        etab_service = _etablissement_de(Service, self.code_service_id)
        if etab_service is not None and etab_service != self.id_etablissement_id:
            raise ValidationError("Le service doit appartenir au même établissement que la chambre.")


class Lit(ValidateOnSaveMixin, EtablissementScopedModel):
    """Identifiant de substitution : id_lit — UUID."""

    id_lit = uuid_pk_field()
    numero_lit = models.CharField(max_length=10)
    id_chambre = models.ForeignKey(
        Chambre,
        on_delete=models.PROTECT,
        db_column="id_chambre",
        related_name="lits",
        help_text="Association CONTENIR.",
    )

    class Meta:
        db_table = "lit"
        verbose_name = "Lit"
        verbose_name_plural = "Lits"
        constraints = [
            models.UniqueConstraint(
                fields=["numero_lit", "id_chambre"],
                name="uniq_lit_numero_chambre",
                violation_error_message="Ce numéro de lit existe déjà dans cette chambre.",
            ),
        ]

    def __str__(self):
        return f"Lit {self.numero_lit}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        etab_chambre = _etablissement_de(Chambre, self.id_chambre_id)
        if etab_chambre is not None and etab_chambre != self.id_etablissement_id:
            raise ValidationError("La chambre doit appartenir au même établissement que le lit.")



class Hospitalisation(ValidateOnSaveMixin, EtablissementScopedModel):
    """
    Sous-type d'Acte (identifiant hérité : id_acte). Décidée lors d'une consultation
    (DECIDER : une consultation débouche sur au plus une hospitalisation).

    Chambre et lit restent vides tant qu'aucun lit n'est disponible : la demande
    est alors « en attente » (RG14). Les hospitalisations terminées sont conservées,
    ce qui garde l'historique d'occupation des lits (RG13).
    """

    id_acte = models.OneToOneField(
        Acte,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="id_acte",
        related_name="hospitalisation",
    )
    date_entree = models.DateField()
    date_sortie = models.DateField(blank=True, null=True)
    id_acte_consultation = models.OneToOneField(
        Consultation,
        on_delete=models.PROTECT,
        db_column="id_acte_consultation",
        related_name="hospitalisation",
        help_text="Association DECIDER.",
    )
    id_chambre = models.ForeignKey(
        Chambre,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_chambre",
        related_name="hospitalisations",
    )
    id_lit = models.ForeignKey(
        Lit,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_lit",
        related_name="hospitalisations",
    )

    class Meta:
        db_table = "hospitalisation"
        verbose_name = "Hospitalisation"
        verbose_name_plural = "Hospitalisations"
        constraints = [
            # RG13 : un lit n'accueille qu'un patient à la fois = au plus une
            # hospitalisation encore ouverte (sans date de sortie) par lit.
            models.UniqueConstraint(
                fields=["id_lit"],
                condition=models.Q(date_sortie__isnull=True, id_lit__isnull=False),
                name="uniq_lit_occupe",
                violation_error_message="Ce lit est déjà occupé par une hospitalisation en cours (RG13).",
            ),
            models.CheckConstraint(
                condition=models.Q(date_sortie__isnull=True) | models.Q(date_sortie__gte=models.F("date_entree")),
                name="chk_hospitalisation_sortie_apres_entree",
                violation_error_message="La date de sortie ne peut pas précéder la date d'entrée.",
            ),
            # Un lit sans sa chambre n'a pas de sens.
            models.CheckConstraint(
                condition=models.Q(id_lit__isnull=True) | models.Q(id_chambre__isnull=False),
                name="chk_hospitalisation_lit_avec_chambre",
                violation_error_message="Un lit ne peut être renseigné sans sa chambre.",
            ),
        ]

    def __str__(self):
        return f"Hospitalisation {self.id_acte_id} (entrée {self.date_entree})"

    def clean(self):
        if self.id_etablissement_id is None:
            return

        acte = Acte.objects.filter(pk=self.id_acte_id).values("id_etablissement_id", "id_patient_id").first()
        if acte and acte["id_etablissement_id"] != self.id_etablissement_id:
            raise ValidationError("L'hospitalisation doit appartenir au même établissement que son acte.")

        consultation = (
            Consultation.objects.filter(pk=self.id_acte_consultation_id)
            .values("id_etablissement_id", "id_acte__id_patient_id")
            .first()
        )
        if consultation:
            if consultation["id_etablissement_id"] != self.id_etablissement_id:
                raise ValidationError("La consultation doit appartenir au même établissement que l'hospitalisation.")
            if acte and consultation["id_acte__id_patient_id"] != acte["id_patient_id"]:
                raise ValidationError("L'hospitalisation doit concerner le patient de la consultation qui la décide.")

        if self.date_sortie is not None and self.date_entree is not None and self.date_sortie < self.date_entree:
            raise ValidationError("La date de sortie ne peut pas précéder la date d'entrée.")

        if self.id_lit_id and not self.id_chambre_id:
            raise ValidationError("Un lit ne peut être renseigné sans sa chambre.")

        etab_chambre = _etablissement_de(Chambre, self.id_chambre_id)
        if etab_chambre is not None and etab_chambre != self.id_etablissement_id:
            raise ValidationError("La chambre doit appartenir au même établissement que l'hospitalisation.")

        if self.id_lit_id:
            lit = Lit.objects.filter(pk=self.id_lit_id).values("id_etablissement_id", "id_chambre_id").first()
            if lit:
                if lit["id_etablissement_id"] != self.id_etablissement_id:
                    raise ValidationError("Le lit doit appartenir au même établissement que l'hospitalisation.")
                if self.id_chambre_id and lit["id_chambre_id"] != self.id_chambre_id:
                    raise ValidationError("Ce lit n'appartient pas à la chambre indiquée.")
