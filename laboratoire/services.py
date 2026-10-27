"""Opérations métier du Bloc 5 et notifications de résultats (RG21-RG23)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.db.rls import current_tenant
from etablissements.models import Etablissement, JournalAction, Medecin, Personnel
from laboratoire.models import Examen, ExamenPrescrit, Notification, ResultatExamen
from soins.models import Acte, Consultation


class LaboratoireError(Exception):
    """Erreur de contexte ou d'opération du laboratoire."""


def _verifier_hopital(id_hopital):
    if current_tenant() != str(id_hopital):
        raise LaboratoireError("La session PostgreSQL doit être positionnée sur l'hôpital courant.")
    if not Etablissement.objects.filter(
        pk=id_hopital, type_etablissement=Etablissement.TYPE_HOPITAL
    ).exists():
        raise LaboratoireError("Le contexte courant n'est pas un hôpital.")


@transaction.atomic
def prescrire_examens(*, id_hopital, matricule_medecin, id_consultation, codes_examens):
    """Prescrit les examens disponibles et retourne séparément ceux absents du catalogue."""
    _verifier_hopital(id_hopital)
    if not codes_examens:
        raise ValidationError({"codes_examens": "Choisissez au moins un examen."})
    if len(codes_examens) != len(set(codes_examens)):
        raise ValidationError({"codes_examens": "Un examen ne peut être demandé qu'une seule fois."})
    try:
        medecin = Medecin.objects.select_related("matricule_personnel").get(pk=matricule_medecin)
    except Medecin.DoesNotExist as exc:
        raise ValidationError({"matricule_medecin": "Le compte médecin lié est introuvable."}) from exc
    if medecin.matricule_personnel.id_etablissement_id != id_hopital:
        raise ValidationError("Le médecin prescripteur doit appartenir à cet hôpital.")
    try:
        consultation = Consultation.objects.select_for_update().select_related("id_acte").get(pk=id_consultation)
    except Consultation.DoesNotExist as exc:
        raise ValidationError({"id_acte_consultation": "Consultation introuvable dans cet hôpital."}) from exc
    if consultation.statut_episode != Consultation.EN_COURS:
        raise ValidationError("Une consultation clôturée ne peut recevoir de nouvelle prescription.")
    if consultation.matricule_personnel_id != medecin.pk:
        raise ValidationError("La prescription doit être signée par le médecin responsable de la consultation (RG10).")

    catalog = {exam.code_examen: exam for exam in Examen.objects.filter(code_examen__in=codes_examens)}
    disponibles = [catalog[code] for code in codes_examens if code in catalog]
    indisponibles = [code for code in codes_examens if code not in catalog]
    prescriptions = []
    for examen in disponibles:
        acte = Acte.objects.create(
            date_acte=timezone.localdate(),
            libelle_acte=examen.libelle_examen,
            montant_base=examen.tarif,
            id_patient_id=consultation.id_acte.id_patient_id,
            id_etablissement_id=id_hopital,
        )
        prescriptions.append(
            ExamenPrescrit.objects.create(
                id_acte=acte,
                date_prescription_examen=timezone.localdate(),
                id_acte_consultation=consultation,
                id_examen=examen,
                matricule_medecin_prescripteur=medecin,
                id_etablissement_id=id_hopital,
            )
        )
    if prescriptions:
        JournalAction.objects.create(
            type_action="prescription_examen",
            details=f"{len(prescriptions)} examen(s) prescrit(s) depuis la consultation {consultation.pk}",
            matricule_personnel=medecin.matricule_personnel,
            id_etablissement_id=id_hopital,
        )
    return prescriptions, indisponibles


@transaction.atomic
def enregistrer_resultat(*, id_hopital, id_acte_examen, matricule_technicien, contenu_resultat):
    """Enregistre le résultat une fois et crée la notification du prescripteur."""
    _verifier_hopital(id_hopital)
    try:
        technicien = Personnel.objects.get(pk=matricule_technicien)
    except Personnel.DoesNotExist as exc:
        raise ValidationError({"matricule_technicien": "Technicien introuvable."}) from exc
    if technicien.id_etablissement_id != id_hopital or technicien.role_metier != "technicien_labo":
        raise ValidationError("Seul un technicien de laboratoire de cet hôpital peut enregistrer le résultat.")
    try:
        examen_prescrit = (
            ExamenPrescrit.objects.select_for_update()
            .select_related("id_examen", "matricule_medecin_prescripteur__matricule_personnel")
            .get(pk=id_acte_examen)
        )
    except ExamenPrescrit.DoesNotExist as exc:
        raise ValidationError({"id_acte_examen_prescrit": "Examen prescrit introuvable."}) from exc
    if hasattr(examen_prescrit, "resultat"):
        raise ValidationError({"resultat": "Un résultat existe déjà pour cet examen prescrit."})

    examen_prescrit.date_realisation = timezone.localdate()
    examen_prescrit.matricule_technicien = technicien
    examen_prescrit.save(update_fields=("date_realisation", "matricule_technicien"))
    resultat = ResultatExamen.objects.create(
        contenu_resultat=contenu_resultat or None,
        date_disponibilite=timezone.localdate(),
        id_acte_examen_prescrit=examen_prescrit,
        id_etablissement_id=id_hopital,
    )
    Notification.objects.create(
        type_notification=Notification.RESULTAT_DISPONIBLE,
        contenu=f"Le résultat de l'examen {examen_prescrit.id_examen.libelle_examen} est disponible.",
        matricule_personnel_destinataire=examen_prescrit.matricule_medecin_prescripteur.matricule_personnel,
        id_resultat_examen=resultat,
        id_etablissement_id=id_hopital,
    )
    JournalAction.objects.create(
        type_action="resultat_examen",
        details=f"Résultat disponible pour l'examen prescrit {examen_prescrit.pk}",
        matricule_personnel=technicien,
        id_etablissement_id=id_hopital,
    )
    return resultat
