"""Bloc 4 — catalogue, prescriptions et délivrances pharmaceutiques."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Etablissement, Medecin, Personnel, Pharmacie as PharmacieEtablissement
from patients.models import Client, Patient
from soins.models import Consultation


def _etablissement_de(modele, pk):
    if pk is None:
        return None
    return modele.objects.filter(pk=pk).values_list("id_etablissement_id", flat=True).first()


def _etablissement_du_medecin(matricule):
    if matricule is None:
        return None
    return (
        Medecin.objects.filter(pk=matricule)
        .values_list("matricule_personnel__id_etablissement_id", flat=True)
        .first()
    )


class Medicament(ValidateOnSaveMixin, EtablissementScopedModel):
    """Un médicament appartient au catalogue d'un seul établissement (RG34)."""

    id_medicament = uuid_pk_field()
    code_medicament = models.CharField(max_length=20)
    nom_medicament = models.CharField(max_length=80)
    dosage = models.CharField(max_length=40)
    forme = models.CharField(max_length=40)
    prix_catalogue = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    seuil_alerte = models.PositiveIntegerField()
    vente_libre = models.BooleanField(default=False)

    class Meta:
        db_table = "medicament"
        verbose_name = "Médicament"
        verbose_name_plural = "Médicaments"
        constraints = [
            models.UniqueConstraint(
                fields=["code_medicament", "id_etablissement"],
                name="uniq_medicament_code_etablissement",
            ),
            models.CheckConstraint(
                condition=models.Q(prix_catalogue__gte=0), name="chk_medicament_prix_non_negatif"
            ),
            models.CheckConstraint(
                condition=models.Q(seuil_alerte__gte=0), name="chk_medicament_seuil_non_negatif"
            ),
        ]

    def __str__(self):
        return f"{self.nom_medicament} {self.dosage}"

    @property
    def quantite_stock(self):
        """Stock vendable recalculé depuis les lots non périmés."""
        return self.lots.filter(date_peremption__gte=timezone.localdate()).aggregate(
            total=models.Sum("quantite_stock")
        )["total"] or 0


class LotMedicament(ValidateOnSaveMixin, EtablissementScopedModel):
    id_lot = uuid_pk_field()
    numero_lot = models.CharField(max_length=30)
    date_peremption = models.DateField()
    quantite_stock = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    id_medicament = models.ForeignKey(
        Medicament,
        on_delete=models.PROTECT,
        db_column="id_medicament",
        related_name="lots",
    )

    class Meta:
        db_table = "lot_medicament"
        verbose_name = "Lot de médicament"
        verbose_name_plural = "Lots de médicaments"
        constraints = [
            models.UniqueConstraint(
                fields=["id_medicament", "numero_lot"], name="uniq_lot_numero_medicament"
            ),
            models.CheckConstraint(condition=models.Q(quantite_stock__gte=0), name="chk_lot_stock_non_negatif"),
        ]
        ordering = ["date_peremption", "numero_lot"]

    def __str__(self):
        return f"{self.numero_lot} — {self.id_medicament}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        etablissement_medicament = _etablissement_de(Medicament, self.id_medicament_id)
        if etablissement_medicament is not None and etablissement_medicament != self.id_etablissement_id:
            raise ValidationError("Le lot et le médicament doivent appartenir au même établissement.")


class Prescription(ValidateOnSaveMixin, EtablissementScopedModel):
    """Prescription interne rédigée lors d'une consultation (RG15)."""

    id_prescription = uuid_pk_field()
    date_prescription = models.DateField()
    matricule_personnel = models.ForeignKey(
        Medecin,
        on_delete=models.PROTECT,
        db_column="matricule_personnel",
        related_name="prescriptions",
    )
    id_patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        db_column="id_patient",
        related_name="prescriptions",
    )
    id_acte_consultation = models.ForeignKey(
        Consultation,
        on_delete=models.PROTECT,
        db_column="id_acte_consultation",
        related_name="prescriptions",
    )

    class Meta:
        db_table = "prescription"
        verbose_name = "Prescription"
        verbose_name_plural = "Prescriptions"

    def __str__(self):
        return f"Prescription {self.id_prescription} — {self.id_patient}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Une prescription interne doit appartenir à un hôpital.")

        etablissement_patient = _etablissement_de(Patient, self.id_patient_id)
        if etablissement_patient is not None and etablissement_patient != self.id_etablissement_id:
            raise ValidationError("Le patient et la prescription doivent appartenir au même hôpital.")

        consultation = (
            Consultation.objects.filter(pk=self.id_acte_consultation_id)
            .values("id_etablissement_id", "id_acte__id_patient_id")
            .first()
        )
        if consultation:
            if consultation["id_etablissement_id"] != self.id_etablissement_id:
                raise ValidationError("La consultation doit appartenir au même hôpital que la prescription.")
            if consultation["id_acte__id_patient_id"] != self.id_patient_id:
                raise ValidationError("La prescription doit concerner le patient de la consultation.")

        etablissement_medecin = _etablissement_du_medecin(self.matricule_personnel_id)
        if etablissement_medecin is not None and etablissement_medecin != self.id_etablissement_id:
            raise ValidationError("Le médecin et la prescription doivent appartenir au même hôpital.")


class LignePrescription(ValidateOnSaveMixin, EtablissementScopedModel):
    id_ligne_prescription = uuid_pk_field()
    id_prescription = models.ForeignKey(
        Prescription,
        on_delete=models.CASCADE,
        db_column="id_prescription",
        related_name="lignes",
    )
    id_medicament = models.ForeignKey(
        Medicament,
        on_delete=models.PROTECT,
        db_column="id_medicament",
        related_name="lignes_prescription",
    )
    posologie = models.CharField(max_length=50)
    quantite_prescrite = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    duree_traitement = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        db_table = "ligne_prescription"
        verbose_name = "Ligne de prescription"
        verbose_name_plural = "Lignes de prescription"
        constraints = [
            models.UniqueConstraint(
                fields=["id_prescription", "id_medicament"], name="uniq_ligne_prescription_medicament"
            ),
            models.CheckConstraint(condition=models.Q(quantite_prescrite__gt=0), name="chk_ligne_prescription_quantite"),
            models.CheckConstraint(condition=models.Q(duree_traitement__gt=0), name="chk_ligne_prescription_duree"),
        ]

    def __str__(self):
        return f"{self.id_medicament} — {self.posologie}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        id_etablissement_prescription = _etablissement_de(Prescription, self.id_prescription_id)
        if id_etablissement_prescription is not None and id_etablissement_prescription != self.id_etablissement_id:
            raise ValidationError("La ligne et la prescription doivent appartenir au même établissement.")
        id_etablissement_medicament = _etablissement_de(Medicament, self.id_medicament_id)
        if id_etablissement_medicament is not None and id_etablissement_medicament != self.id_etablissement_id:
            raise ValidationError("La ligne et le médicament doivent appartenir au même établissement.")


class Vente(EtablissementScopedModel):
    """Une vente de pharmacie cible un patient OU un client, jamais les deux."""

    PAYE = "paye"
    ANNULE = "annule"
    STATUT_PAIEMENT_CHOICES = [(PAYE, "Payée"), (ANNULE, "Annulée")]

    ESPECES = "especes"
    MOBILE_MONEY = "mobile_money"
    CARTE = "carte"
    MOYEN_PAIEMENT_CHOICES = [
        (ESPECES, "Espèces"),
        (MOBILE_MONEY, "Mobile money"),
        (CARTE, "Carte"),
    ]

    id_vente = uuid_pk_field()
    date_vente = models.DateTimeField(default=timezone.now)
    id_patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_patient",
        related_name="ventes_pharmacie",
    )
    id_client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_client",
        related_name="ventes",
    )
    id_prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="id_prescription",
        related_name="ventes",
    )
    nom_prescripteur_externe = models.CharField(max_length=80, blank=True, null=True)
    date_prescription_externe = models.DateField(blank=True, null=True)
    statut_paiement = models.CharField(
        max_length=15, choices=STATUT_PAIEMENT_CHOICES, blank=True, null=True
    )
    moyen_paiement = models.CharField(max_length=20, choices=MOYEN_PAIEMENT_CHOICES, blank=True, null=True)
    matricule_personnel = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        db_column="matricule_personnel",
        related_name="ventes_pharmacie",
    )

    class Meta:
        db_table = "vente"
        verbose_name = "Vente"
        verbose_name_plural = "Ventes"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(id_patient__isnull=False) & models.Q(id_client__isnull=True))
                    | (models.Q(id_patient__isnull=True) & models.Q(id_client__isnull=False))
                ),
                name="chk_vente_patient_ou_client",
                violation_error_message="Une vente concerne exactement un patient ou un client.",
            ),
            models.CheckConstraint(
                condition=~(
                    models.Q(id_prescription__isnull=False)
                    & models.Q(nom_prescripteur_externe__isnull=False)
                    & ~models.Q(nom_prescripteur_externe="")
                ),
                name="chk_vente_prescription_interne_ou_externe",
            ),
        ]

    def __str__(self):
        return f"Vente {self.id_vente} — {self.date_vente:%Y-%m-%d %H:%M}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        try:
            pharmacie = PharmacieEtablissement.objects.get(pk=self.id_etablissement_id)
        except PharmacieEtablissement.DoesNotExist:
            raise ValidationError("Une vente doit appartenir à une pharmacie.")

        rattachee = bool(pharmacie.id_etablissement_hopital_rattachement_id)

        if bool(self.id_patient_id) == bool(self.id_client_id):
            raise ValidationError("Une vente concerne exactement un patient ou un client.")

        if rattachee:
            if not self.id_patient_id or not self.id_prescription_id:
                raise ValidationError("En pharmacie hospitalière, patient et prescription interne sont obligatoires (RG19-a).")
            if self.statut_paiement:
                raise ValidationError("Le statut de paiement de la vente est réservé à la pharmacie indépendante.")
        else:
            if self.id_patient_id:
                raise ValidationError("Une pharmacie indépendante rattache la vente à un client (RG31).")
            # Décision D5 : l'encaissement se fait au comptoir, donc statut et moyen sont obligatoires.
            if not self.statut_paiement:
                raise ValidationError("Le statut de paiement est obligatoire pour une vente en pharmacie indépendante.")
            if self.statut_paiement not in dict(self.STATUT_PAIEMENT_CHOICES):
                raise ValidationError("Statut de paiement inconnu.")
            if not self.moyen_paiement:
                raise ValidationError("Le moyen de paiement est obligatoire pour une vente en pharmacie indépendante.")

    def save(self, *args, **kwargs):
        # Comme ValidateOnSaveMixin, mais sans valider l'existence de id_patient et id_prescription :
        # pour une pharmacie rattachée, ces lignes appartiennent à l'hôpital et la RLS les rend
        # invisibles depuis la pharmacie. Leur existence est garantie par la clé étrangère en base.
        self.full_clean(exclude={"id_patient", "id_prescription"})
        super().save(*args, **kwargs)


class LigneVente(ValidateOnSaveMixin, EtablissementScopedModel):
    id_ligne_vente = uuid_pk_field()
    id_vente = models.ForeignKey(Vente, on_delete=models.CASCADE, db_column="id_vente", related_name="lignes")
    id_medicament = models.ForeignKey(
        Medicament,
        on_delete=models.PROTECT,
        db_column="id_medicament",
        related_name="lignes_vente",
    )
    id_lot = models.ForeignKey(
        LotMedicament,
        on_delete=models.PROTECT,
        db_column="id_lot",
        related_name="lignes_vente",
    )
    quantite_demandee = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantite_delivree = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    prix_facture = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )

    class Meta:
        db_table = "ligne_vente"
        verbose_name = "Ligne de vente"
        verbose_name_plural = "Lignes de vente"
        constraints = [
            models.UniqueConstraint(
                fields=["id_vente", "id_medicament", "id_lot"], name="uniq_ligne_vente_medicament_lot"
            ),
            models.CheckConstraint(condition=models.Q(quantite_demandee__gt=0), name="chk_ligne_vente_demandee_positive"),
            models.CheckConstraint(
                condition=models.Q(quantite_delivree__gte=0), name="chk_ligne_vente_delivree_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(quantite_delivree__lte=models.F("quantite_demandee")),
                name="chk_ligne_vente_delivree_inferieure_demande",
            ),
            models.CheckConstraint(condition=models.Q(prix_facture__gte=0), name="chk_ligne_vente_prix_non_negatif"),
        ]

    def __str__(self):
        return f"{self.id_medicament} — lot {self.id_lot_id}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        for modele, pk, libelle in (
            (Vente, self.id_vente_id, "vente"),
            (Medicament, self.id_medicament_id, "médicament"),
            (LotMedicament, self.id_lot_id, "lot"),
        ):
            etablissement_associe = _etablissement_de(modele, pk)
            if etablissement_associe is not None and etablissement_associe != self.id_etablissement_id:
                raise ValidationError(f"La ligne et le {libelle} doivent appartenir à la même pharmacie.")
        if self.id_medicament_id and self.id_lot_id:
            lot = LotMedicament.objects.filter(pk=self.id_lot_id).values_list("id_medicament_id", flat=True).first()
            if lot and lot != self.id_medicament_id:
                raise ValidationError("Le lot doit correspondre au médicament vendu.")

        # RG38 (filet de sécurité) : un médicament hors vente libre exige une prescription interne
        # ou un prescripteur externe identifié (nom ET date, décision D2).
        if self.id_vente_id and self.id_medicament_id:
            vente = (
                Vente.objects.filter(pk=self.id_vente_id)
                .values("id_prescription", "nom_prescripteur_externe", "date_prescription_externe")
                .first()
            )
            vente_libre = (
                Medicament.objects.filter(pk=self.id_medicament_id).values_list("vente_libre", flat=True).first()
            )
            if vente is not None and vente_libre is False:
                prescription_interne = vente["id_prescription"] is not None
                prescripteur_externe = bool(vente["nom_prescripteur_externe"]) and vente["date_prescription_externe"] is not None
                if not (prescription_interne or prescripteur_externe):
                    raise ValidationError(
                        "Ce médicament n'est pas en vente libre : prescription interne ou prescripteur externe "
                        "(nom et date) obligatoire (RG38)."
                    )