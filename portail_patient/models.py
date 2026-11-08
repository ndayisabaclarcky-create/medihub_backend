"""Bloc 7 — codes temporaires pour l'accès sans compte au portail patient."""

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Etablissement
from patients.models import Patient


class CodeVerification(ValidateOnSaveMixin, EtablissementScopedModel):
    """Code à usage unique et durée limitée (RG41), sans compte patient permanent."""

    id_code = uuid_pk_field()
    code = models.CharField(
        max_length=6,
        validators=[RegexValidator(r"^\d{6}$", "Le code doit comporter exactement six chiffres.")],
    )
    date_generation = models.DateTimeField(default=timezone.now)
    date_expiration = models.DateTimeField()
    utilise = models.BooleanField(default=False)
    id_patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        db_column="id_patient",
        related_name="codes_verification_portail",
    )

    class Meta:
        db_table = "code_verification"
        verbose_name = "Code d'accès au portail patient"
        verbose_name_plural = "Codes d'accès au portail patient"
        ordering = ("-date_generation",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(date_expiration__gt=models.F("date_generation")),
                name="chk_code_expiration_apres_generation",
            ),
        ]

    def __str__(self):
        return f"Code portail {self.id_code}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Un code portail ne peut être délivré que par un hôpital.")
        if self.id_patient_id and self.id_patient.id_etablissement_id != self.id_etablissement_id:
            raise ValidationError("Le patient et le code doivent appartenir au même hôpital.")
        if self.date_expiration and self.date_generation and self.date_expiration <= self.date_generation:
            raise ValidationError("Le code doit expirer après sa génération.")


class AccesDocumentPatient(ValidateOnSaveMixin, EtablissementScopedModel):
    """Trace la consultation ou le téléchargement d'un document par le patient."""

    CONSULTATION = "consultation"
    TELECHARGEMENT = "telechargement"
    ACTION_CHOICES = [(CONSULTATION, "Consultation"), (TELECHARGEMENT, "Téléchargement")]
    RESULTAT = "resultat_examen"
    PRESCRIPTION = "prescription"
    FACTURE = "facture"
    TYPE_CHOICES = [
        (RESULTAT, "Résultat d'examen"),
        (PRESCRIPTION, "Prescription"),
        (FACTURE, "Facture"),
    ]

    id_acces = uuid_pk_field()
    id_patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, db_column="id_patient", related_name="acces_documents"
    )
    type_document = models.CharField(max_length=20, choices=TYPE_CHOICES)
    id_document = models.UUIDField()
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    date_acces = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "acces_document_patient"
        ordering = ("-date_acces",)

    def clean(self):
        if self.id_patient_id and self.id_etablissement_id:
            if self.id_patient.id_etablissement_id != self.id_etablissement_id:
                raise ValidationError("Le journal et le patient doivent appartenir au même établissement.")
