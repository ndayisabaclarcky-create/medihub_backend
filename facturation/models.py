"""Bloc 6 — facture par épisode hospitalier et paiements échelonnés."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Etablissement, Personnel
from patients.models import Patient
from pharmacie.models import LigneVente
from soins.models import Acte, Consultation


class Facture(ValidateOnSaveMixin, EtablissementScopedModel):
    EMISE = "emise"
    PARTIELLEMENT_PAYEE = "partiellement_payee"
    SOLDEE = "soldee"
    STATUT_CHOICES = [
        (EMISE, "Émise"),
        (PARTIELLEMENT_PAYEE, "Partiellement payée"),
        (SOLDEE, "Soldée"),
    ]

    id_facture = uuid_pk_field()
    date_emission = models.DateField(default=timezone.localdate)
    id_patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, db_column="id_patient", related_name="factures"
    )
    id_acte_consultation = models.OneToOneField(
        Consultation,
        on_delete=models.PROTECT,
        db_column="id_acte_consultation",
        related_name="facture",
    )
    statut_facture = models.CharField(max_length=20, choices=STATUT_CHOICES, default=EMISE)

    class Meta:
        db_table = "facture"
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ("-date_emission", "-id_facture")

    def __str__(self):
        return f"Facture {self.id_facture} — {self.date_emission}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Une facture d'épisode est émise par un hôpital.")
        if self.id_patient_id and self.id_patient.id_etablissement_id != self.id_etablissement_id:
            raise ValidationError("Le patient facturé doit appartenir à cet hôpital.")
        if self.id_acte_consultation_id:
            consultation = Consultation.objects.filter(pk=self.id_acte_consultation_id).values(
                "id_etablissement_id", "id_acte__id_patient_id", "statut_episode"
            ).first()
            if consultation:
                if consultation["id_etablissement_id"] != self.id_etablissement_id:
                    raise ValidationError("La consultation doit appartenir au même hôpital.")
                if consultation["id_acte__id_patient_id"] != self.id_patient_id:
                    raise ValidationError("La facture doit concerner le patient de la consultation-ancre.")
                if consultation["statut_episode"] != Consultation.CLOS:
                    raise ValidationError("Une facture ne peut être émise que pour un épisode clôturé.")

    @property
    def montant_total(self):
        return self.lignes.aggregate(total=Sum("montant_ligne"))["total"] or Decimal("0.00")

    @property
    def taux_prise_en_charge(self):
        assurance_id = Patient.objects.filter(pk=self.id_patient_id).values_list("id_assurance_id", flat=True).first()
        if not assurance_id:
            return Decimal("0.00")
        from patients.models import Assurance

        taux = Assurance.objects.filter(pk=assurance_id, id_etablissement_id=self.id_etablissement_id).values_list(
            "taux_prise_en_charge", flat=True
        ).first()
        return taux or Decimal("0.00")

    @property
    def montant_assurance(self):
        return (self.montant_total * self.taux_prise_en_charge / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def montant_patient(self):
        return self.montant_total - self.montant_assurance

    @property
    def total_paye(self):
        return self.paiements.aggregate(total=Sum("montant_paye"))["total"] or Decimal("0.00")

    @property
    def solde_patient(self):
        return max(self.montant_patient - self.total_paye, Decimal("0.00"))


class LigneFacture(ValidateOnSaveMixin, EtablissementScopedModel):
    id_ligne_facture = uuid_pk_field()
    designation = models.CharField(max_length=80)
    quantite = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    prix_unitaire = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    montant_ligne = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    id_facture = models.ForeignKey(
        Facture, on_delete=models.CASCADE, db_column="id_facture", related_name="lignes"
    )
    id_acte = models.ForeignKey(
        Acte,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_acte",
        related_name="lignes_facture",
    )
    id_ligne_vente = models.ForeignKey(
        LigneVente,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_ligne_vente",
        related_name="lignes_facture",
    )

    class Meta:
        db_table = "ligne_facture"
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(id_acte__isnull=False, id_ligne_vente__isnull=True)
                           | models.Q(id_acte__isnull=True, id_ligne_vente__isnull=False)),
                name="chk_ligne_facture_acte_ou_vente",
            ),
            models.CheckConstraint(condition=models.Q(quantite__gt=0), name="chk_ligne_facture_quantite_positive"),
            models.CheckConstraint(condition=models.Q(prix_unitaire__gte=0), name="chk_ligne_facture_prix_non_negatif"),
            models.CheckConstraint(condition=models.Q(montant_ligne__gte=0), name="chk_ligne_facture_montant_non_negatif"),
            models.UniqueConstraint(fields=("id_acte",), condition=models.Q(id_acte__isnull=False), name="uniq_facturation_acte"),
            models.UniqueConstraint(fields=("id_ligne_vente",), condition=models.Q(id_ligne_vente__isnull=False), name="uniq_facturation_ligne_vente"),
        ]

    def __str__(self):
        return self.designation

    def clean(self):
        if self.id_etablissement_id is None:
            return
        if self.id_facture_id and self.id_facture.id_etablissement_id != self.id_etablissement_id:
            raise ValidationError("La ligne et la facture doivent appartenir au même hôpital.")
        if bool(self.id_acte_id) == bool(self.id_ligne_vente_id):
            raise ValidationError("Une ligne facture un acte ou une ligne de vente, jamais les deux.")
        if self.id_acte_id and self.id_acte.id_etablissement_id != self.id_etablissement_id:
            raise ValidationError("L'acte facturé doit appartenir au même hôpital.")
        if self.id_acte_id:
            facture = self.id_facture
            if self.id_acte.id_patient_id != facture.id_patient_id:
                raise ValidationError("L'acte et la facture doivent concerner le même patient.")
            if self.id_acte_id != facture.id_acte_consultation_id:
                from laboratoire.models import ExamenPrescrit
                from soins.models import Hospitalisation

                hospitalisation_episode = Hospitalisation.objects.filter(
                    id_acte_id=self.id_acte_id,
                    id_acte_consultation_id=facture.id_acte_consultation_id,
                ).exists()
                examen_episode = ExamenPrescrit.objects.filter(
                    id_acte_id=self.id_acte_id,
                    id_acte_consultation_id=facture.id_acte_consultation_id,
                ).exists()
                if not (hospitalisation_episode or examen_episode):
                    raise ValidationError("L'acte ne fait pas partie de l'épisode facturé.")
        # Les lignes de vente appartiennent à la pharmacie rattachée (autre
        # tenant). Le service de facturation vérifie leur lien patient/épisode
        # sous le contexte RLS de cette pharmacie avant l'insertion.

    def save(self, *args, **kwargs):
        # ForeignKey.validate() ferait une lecture de LigneVente sous la RLS de
        # l'hôpital et rendrait invisible la ligne d'un tenant pharmacie.
        self.full_clean(exclude={"id_ligne_vente"})
        super().save(*args, **kwargs)


class Paiement(ValidateOnSaveMixin, EtablissementScopedModel):
    ESPECES = "especes"
    MOBILE_MONEY = "mobile_money"
    CARTE = "carte"
    MOYEN_CHOICES = [(ESPECES, "Espèces"), (MOBILE_MONEY, "Mobile money"), (CARTE, "Carte")]

    id_paiement = uuid_pk_field()
    montant_paye = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    date_paiement = models.DateField(default=timezone.localdate)
    moyen_paiement = models.CharField(max_length=20, choices=MOYEN_CHOICES, blank=True, null=True)
    id_facture = models.ForeignKey(Facture, on_delete=models.PROTECT, db_column="id_facture", related_name="paiements")
    matricule_personnel = models.ForeignKey(
        Personnel, on_delete=models.PROTECT, db_column="matricule_personnel", related_name="paiements_enregistres"
    )

    class Meta:
        db_table = "paiement"
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ("date_paiement", "id_paiement")
        constraints = [
            models.CheckConstraint(condition=models.Q(montant_paye__gt=0), name="chk_paiement_montant_positif"),
        ]

    def __str__(self):
        return f"Paiement {self.id_paiement} — {self.montant_paye}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Les paiements de facture sont enregistrés par l'hôpital.")
        if self.id_facture_id and self.id_facture.id_etablissement_id != self.id_etablissement_id:
            raise ValidationError("Le paiement et la facture doivent appartenir au même hôpital.")
        if self.matricule_personnel_id:
            personnel = Personnel.objects.filter(pk=self.matricule_personnel_id).values(
                "id_etablissement_id", "role_metier"
            ).first()
            if personnel and (
                personnel["id_etablissement_id"] != self.id_etablissement_id
                or personnel["role_metier"] not in ("comptable", "administrateur")
            ):
                raise ValidationError("Le paiement doit être enregistré par un comptable ou administrateur de cet hôpital.")
        if self.id_facture_id and self.montant_paye is not None:
            deja_paye = (
                Paiement.objects.filter(id_facture_id=self.id_facture_id)
                .exclude(pk=self.pk)
                .aggregate(total=Sum("montant_paye"))["total"]
                or Decimal("0.00")
            )
            if deja_paye + self.montant_paye > self.id_facture.montant_patient:
                raise ValidationError("Le cumul des paiements ne peut dépasser la part patient de la facture.")
