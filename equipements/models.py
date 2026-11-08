from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Personnel, Service


class Equipement(ValidateOnSaveMixin, EtablissementScopedModel):
    EN_SERVICE = "en_service"
    EN_MAINTENANCE = "en_maintenance"
    HORS_SERVICE = "hors_service"
    RETIRE = "retire"
    ETAT_CHOICES = [
        (EN_SERVICE, "En service"),
        (EN_MAINTENANCE, "En maintenance"),
        (HORS_SERVICE, "Hors service"),
        (RETIRE, "Retiré"),
    ]

    id_equipement = uuid_pk_field()
    code_equipement = models.CharField(max_length=30)
    nom = models.CharField(max_length=80)
    categorie = models.CharField(max_length=40)
    fabricant = models.CharField(max_length=80, blank=True)
    modele = models.CharField(max_length=80, blank=True)
    numero_serie = models.CharField(max_length=80, blank=True)
    emplacement = models.CharField(max_length=120)
    code_service = models.ForeignKey(
        Service, on_delete=models.SET_NULL, blank=True, null=True, db_column="code_service", related_name="equipements"
    )
    date_acquisition = models.DateField(blank=True, null=True)
    date_mise_en_service = models.DateField(blank=True, null=True)
    date_fin_garantie = models.DateField(blank=True, null=True)
    etat = models.CharField(max_length=20, choices=ETAT_CHOICES, default=EN_SERVICE)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equipement"
        ordering = ("nom", "code_equipement")
        constraints = [
            models.UniqueConstraint(fields=("id_etablissement", "code_equipement"), name="uniq_equipement_code_tenant"),
            models.CheckConstraint(
                condition=models.Q(date_fin_garantie__isnull=True)
                | models.Q(date_acquisition__isnull=True)
                | models.Q(date_fin_garantie__gte=models.F("date_acquisition")),
                name="chk_equipement_garantie_apres_achat",
            ),
        ]

    def __str__(self):
        return f"{self.code_equipement} — {self.nom}"

    def clean(self):
        if self.code_service_id and self.id_etablissement_id:
            if self.code_service.id_etablissement_id != self.id_etablissement_id:
                raise ValidationError({"code_service": "Le service doit appartenir au même établissement."})
        if self.date_acquisition and self.date_mise_en_service and self.date_mise_en_service < self.date_acquisition:
            raise ValidationError({"date_mise_en_service": "La mise en service ne peut précéder l'acquisition."})


class InterventionMaintenance(ValidateOnSaveMixin, EtablissementScopedModel):
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    TYPE_CHOICES = [(PREVENTIVE, "Préventive"), (CORRECTIVE, "Corrective")]
    PLANIFIEE = "planifiee"
    REALISEE = "realisee"
    ANNULEE = "annulee"
    STATUT_CHOICES = [(PLANIFIEE, "Planifiée"), (REALISEE, "Réalisée"), (ANNULEE, "Annulée")]

    id_intervention = uuid_pk_field()
    id_equipement = models.ForeignKey(
        Equipement, on_delete=models.PROTECT, db_column="id_equipement", related_name="interventions"
    )
    type_intervention = models.CharField(max_length=15, choices=TYPE_CHOICES)
    statut = models.CharField(max_length=15, choices=STATUT_CHOICES, default=PLANIFIEE)
    date_planifiee = models.DateField()
    date_realisation = models.DateField(blank=True, null=True)
    description = models.CharField(max_length=500)
    cout = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    matricule_technicien = models.ForeignKey(
        Personnel,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        db_column="matricule_technicien",
        related_name="interventions_equipements",
    )
    prochaine_echeance = models.DateField(blank=True, null=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intervention_maintenance"
        ordering = ("date_planifiee", "id_intervention")
        constraints = [
            models.CheckConstraint(condition=models.Q(cout__gte=0), name="chk_intervention_cout_non_negatif"),
            models.CheckConstraint(
                condition=models.Q(date_realisation__isnull=True)
                | models.Q(date_realisation__gte=models.F("date_planifiee")),
                name="chk_intervention_realisation_coherente",
            ),
        ]

    def __str__(self):
        return f"{self.get_type_intervention_display()} — {self.id_equipement} — {self.date_planifiee}"

    def clean(self):
        if self.id_equipement_id and self.id_etablissement_id:
            if self.id_equipement.id_etablissement_id != self.id_etablissement_id:
                raise ValidationError({"id_equipement": "L'équipement doit appartenir au même établissement."})
        if self.matricule_technicien_id and self.id_etablissement_id:
            if self.matricule_technicien.id_etablissement_id != self.id_etablissement_id:
                raise ValidationError({"matricule_technicien": "Le technicien doit appartenir au même établissement."})
        if self.date_realisation and self.date_realisation < self.date_planifiee:
            raise ValidationError({"date_realisation": "La réalisation ne peut précéder la date planifiée."})
        if self.statut == self.REALISEE and not self.date_realisation:
            self.date_realisation = timezone.localdate()
        if self.statut != self.REALISEE and self.date_realisation:
            raise ValidationError({"date_realisation": "Une intervention non réalisée ne doit pas avoir de date de réalisation."})
