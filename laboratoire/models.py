"""Bloc 5 — catalogue d'examens, prescriptions, résultats et notifications."""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import EtablissementScopedModel, ValidateOnSaveMixin, uuid_pk_field
from etablissements.models import Etablissement, Medecin, Personnel
from soins.models import Acte, Consultation


def _etablissement_de(modele, pk):
    if pk is None:
        return None
    return modele.objects.filter(pk=pk).values_list("id_etablissement_id", flat=True).first()


class Examen(ValidateOnSaveMixin, EtablissementScopedModel):
    """Examen réalisable et tarifé au catalogue d'un hôpital (RG22, RG34)."""

    id_examen = uuid_pk_field()
    code_examen = models.CharField(max_length=20)
    libelle_examen = models.CharField(max_length=60)
    tarif = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        db_table = "examen"
        verbose_name = "Examen de laboratoire"
        verbose_name_plural = "Examens de laboratoire"
        constraints = [
            models.UniqueConstraint(fields=("code_examen", "id_etablissement"), name="uniq_examen_code_etablissement"),
            models.CheckConstraint(condition=models.Q(tarif__gte=0), name="chk_examen_tarif_non_negatif"),
        ]
        ordering = ("libelle_examen", "code_examen")

    def __str__(self):
        return f"{self.code_examen} — {self.libelle_examen}"

    def clean(self):
        if self.id_etablissement_id and self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Le catalogue d'examens appartient à un hôpital.")


class ExamenPrescrit(ValidateOnSaveMixin, EtablissementScopedModel):
    """Examen demandé depuis une consultation et facturable comme un Acte."""

    id_acte = models.OneToOneField(
        Acte, on_delete=models.CASCADE, primary_key=True, db_column="id_acte", related_name="examen_prescrit"
    )
    date_prescription_examen = models.DateField(default=timezone.localdate)
    date_realisation = models.DateField(blank=True, null=True)
    id_acte_consultation = models.ForeignKey(
        Consultation, on_delete=models.PROTECT, db_column="id_acte_consultation", related_name="examens_prescrits"
    )
    id_examen = models.ForeignKey(
        Examen, on_delete=models.PROTECT, db_column="id_examen", related_name="prescriptions"
    )
    matricule_medecin_prescripteur = models.ForeignKey(
        Medecin, on_delete=models.PROTECT, db_column="matricule_medecin_prescripteur", related_name="examens_prescrits"
    )
    matricule_technicien = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        db_column="matricule_technicien",
        related_name="examens_realises",
    )

    class Meta:
        db_table = "examen_prescrit"
        verbose_name = "Examen prescrit"
        verbose_name_plural = "Examens prescrits"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(date_realisation__isnull=True)
                | models.Q(date_realisation__gte=models.F("date_prescription_examen")),
                name="chk_examen_realisation_apres_prescription",
            ),
        ]
        ordering = ("-date_prescription_examen",)

    def __str__(self):
        return f"{self.id_examen} — demande {self.id_acte_id}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        if self.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise ValidationError("Un examen prescrit appartient à un hôpital.")
        acte = Acte.objects.filter(pk=self.id_acte_id).values("id_etablissement_id", "id_patient_id").first()
        consultation = Consultation.objects.filter(pk=self.id_acte_consultation_id).values(
            "id_etablissement_id", "id_acte__id_patient_id"
        ).first()
        if acte and acte["id_etablissement_id"] != self.id_etablissement_id:
            raise ValidationError("L'acte d'examen doit appartenir au même hôpital.")
        if consultation:
            if consultation["id_etablissement_id"] != self.id_etablissement_id:
                raise ValidationError("La consultation doit appartenir au même hôpital.")
            if acte and acte["id_patient_id"] != consultation["id_acte__id_patient_id"]:
                raise ValidationError("L'examen et sa consultation doivent concerner le même patient.")
        if _etablissement_de(Examen, self.id_examen_id) not in (None, self.id_etablissement_id):
            raise ValidationError("L'examen doit appartenir au catalogue de cet hôpital (RG22).")
        etab_medecin = Medecin.objects.filter(pk=self.matricule_medecin_prescripteur_id).values_list(
            "matricule_personnel__id_etablissement_id", flat=True
        ).first()
        if etab_medecin not in (None, self.id_etablissement_id):
            raise ValidationError("Le médecin prescripteur doit appartenir à cet hôpital.")
        if self.matricule_technicien_id:
            technicien = Personnel.objects.filter(pk=self.matricule_technicien_id).values(
                "id_etablissement_id", "role_metier"
            ).first()
            if technicien and (technicien["id_etablissement_id"] != self.id_etablissement_id or technicien["role_metier"] != "technicien_labo"):
                raise ValidationError("La réalisation doit être attribuée à un technicien de laboratoire de cet hôpital.")
        if self.date_realisation and self.date_realisation < self.date_prescription_examen:
            raise ValidationError("La date de réalisation ne peut précéder la prescription.")


class ResultatExamen(ValidateOnSaveMixin, EtablissementScopedModel):
    id_resultat = uuid_pk_field()
    contenu_resultat = models.CharField(max_length=300, blank=True, null=True)
    date_disponibilite = models.DateField(blank=True, null=True)
    id_acte_examen_prescrit = models.OneToOneField(
        ExamenPrescrit,
        on_delete=models.CASCADE,
        db_column="id_acte_examen_prescrit",
        related_name="resultat",
    )

    class Meta:
        db_table = "resultat_examen"
        verbose_name = "Résultat d'examen"
        verbose_name_plural = "Résultats d'examen"

    def __str__(self):
        return f"Résultat {self.id_resultat} — {self.id_acte_examen_prescrit_id}"

    def clean(self):
        if self.id_etablissement_id is None:
            return
        if _etablissement_de(ExamenPrescrit, self.id_acte_examen_prescrit_id) not in (None, self.id_etablissement_id):
            raise ValidationError("Le résultat et l'examen prescrit doivent appartenir au même hôpital.")
        if self.date_disponibilite is None:
            self.date_disponibilite = timezone.localdate()


class Notification(ValidateOnSaveMixin, EtablissementScopedModel):
    RESULTAT_DISPONIBLE = "resultat_disponible"
    TYPE_CHOICES = [(RESULTAT_DISPONIBLE, "Résultat d'examen disponible")]

    id_notification = uuid_pk_field()
    type_notification = models.CharField(max_length=30, choices=TYPE_CHOICES)
    contenu = models.CharField(max_length=300)
    date_creation = models.DateTimeField(default=timezone.now)
    lue = models.BooleanField(default=False)
    date_lecture = models.DateTimeField(blank=True, null=True)
    matricule_personnel_destinataire = models.ForeignKey(
        Personnel,
        on_delete=models.PROTECT,
        db_column="matricule_personnel_destinataire",
        related_name="notifications_laboratoire",
    )
    id_resultat_examen = models.OneToOneField(
        ResultatExamen,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        db_column="id_resultat_examen",
        related_name="notification",
    )

    class Meta:
        db_table = "notification"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ("-date_creation",)
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(lue=False, date_lecture__isnull=True) | models.Q(lue=True, date_lecture__isnull=False)),
                name="chk_notification_lecture_coherente",
            ),
        ]

    def __str__(self):
        return self.contenu

    def clean(self):
        if self.id_etablissement_id is None:
            return
        destinataire_etablissement = Personnel.objects.filter(pk=self.matricule_personnel_destinataire_id).values_list(
            "id_etablissement_id", flat=True
        ).first()
        if destinataire_etablissement not in (None, self.id_etablissement_id):
            raise ValidationError("Le destinataire doit appartenir au même hôpital que la notification.")
        if _etablissement_de(ResultatExamen, self.id_resultat_examen_id) not in (None, self.id_etablissement_id):
            raise ValidationError("Le résultat et la notification doivent appartenir au même hôpital.")
        if self.lue and self.date_lecture is None:
            self.date_lecture = timezone.now()
        elif not self.lue:
            self.date_lecture = None
