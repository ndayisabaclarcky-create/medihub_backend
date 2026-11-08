from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Etablissement, Personnel


class Partenariat(ValidateOnSaveMixin, EtablissementScopedModel):
    """Accord entre deux établissements, sans partage implicite de données patients."""

    EN_ATTENTE = "en_attente"
    ACTIF = "actif"
    REFUSE = "refuse"
    SUSPENDU = "suspendu"
    TERMINE = "termine"
    STATUT_CHOICES = [
        (EN_ATTENTE, "En attente"),
        (ACTIF, "Actif"),
        (REFUSE, "Refusé"),
        (SUSPENDU, "Suspendu"),
        (TERMINE, "Terminé"),
    ]

    id_partenariat = uuid_pk_field()
    id_etablissement_partenaire = models.ForeignKey(
        Etablissement,
        on_delete=models.PROTECT,
        db_column="id_etablissement_partenaire",
        related_name="partenariats_recus",
    )
    type_partenariat = models.CharField(max_length=40)
    date_debut = models.DateField(default=timezone.localdate)
    date_fin = models.DateField(blank=True, null=True)
    statut = models.CharField(max_length=15, choices=STATUT_CHOICES, default=EN_ATTENTE)
    description = models.CharField(max_length=500, blank=True)
    matricule_proposant = models.ForeignKey(
        Personnel, on_delete=models.PROTECT, db_column="matricule_proposant", related_name="partenariats_proposes"
    )
    matricule_validateur = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="matricule_validateur",
        related_name="partenariats_valides",
    )
    date_validation = models.DateTimeField(blank=True, null=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "partenariat"
        ordering = ("-date_creation",)
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(id_etablissement=models.F("id_etablissement_partenaire")),
                name="chk_partenariat_deux_etablissements",
            ),
            models.CheckConstraint(
                condition=models.Q(date_fin__isnull=True) | models.Q(date_fin__gte=models.F("date_debut")),
                name="chk_partenariat_dates_coherentes",
            ),
            models.UniqueConstraint(
                fields=("id_etablissement", "id_etablissement_partenaire", "type_partenariat", "date_debut"),
                name="uniq_partenariat_type_debut",
            ),
        ]

    def __str__(self):
        return f"{self.id_etablissement} — {self.type_partenariat} — {self.id_etablissement_partenaire}"

    def clean(self):
        if self.id_etablissement_id and self.id_etablissement_partenaire_id == self.id_etablissement_id:
            raise ValidationError({"id_etablissement_partenaire": "Un établissement ne peut pas être partenaire de lui-même."})
        if self.date_fin and self.date_debut and self.date_fin < self.date_debut:
            raise ValidationError({"date_fin": "La fin du partenariat doit suivre son début."})
        if self.matricule_proposant_id:
            proposant = Personnel.objects.filter(pk=self.matricule_proposant_id).values(
                "id_etablissement_id", "role_metier"
            ).first()
            if proposant and (
                proposant["id_etablissement_id"] != self.id_etablissement_id
                or proposant["role_metier"] != "administrateur"
            ):
                raise ValidationError({"matricule_proposant": "La proposition doit venir d'un administrateur de l'établissement initiateur."})
        if self.matricule_validateur_id:
            validateur = Personnel.objects.filter(pk=self.matricule_validateur_id).values(
                "id_etablissement_id", "role_metier"
            ).first()
            if validateur and (
                validateur["id_etablissement_id"] != self.id_etablissement_partenaire_id
                or validateur["role_metier"] != "administrateur"
            ):
                raise ValidationError({"matricule_validateur": "La validation doit venir d'un administrateur de l'établissement partenaire."})
