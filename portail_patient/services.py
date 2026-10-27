"""Vérification téléphonique et prise de rendez-vous du portail (RG41)."""

import secrets
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.db.rls import current_tenant, temporary_tenant
from etablissements.models import Etablissement, Medecin
from patients.models import Patient, Telephone
from portail_patient.models import CodeVerification
from soins.models import RendezVous


class PortailPatientError(Exception):
    """Erreur d'accès ou d'opération pour le portail patient."""


MESSAGE_CODE_INVALIDE = "Code invalide ou expiré. Demandez un nouveau code."


@transaction.atomic
def demander_code(*, id_hopital, numero_telephone):
    """Génère un code de six chiffres pour un numéro connu dans l'hôpital choisi."""
    telephone = (numero_telephone or "").strip()
    if not telephone:
        raise ValidationError({"numero_telephone": "Le numéro de téléphone est obligatoire."})
    if not Etablissement.objects.filter(
        pk=id_hopital,
        type_etablissement=Etablissement.TYPE_HOPITAL,
    ).exists():
        # Réponse identique pour un hôpital inexistant ou un téléphone inconnu.
        return None

    with temporary_tenant(id_hopital):
        ids_patients = list(
            Telephone.objects.filter(
                id_etablissement_id=id_hopital,
                numero_telephone=telephone,
            ).values_list("id_patient_id", flat=True).distinct()
        )
        # Un numéro rattaché à plusieurs dossiers est ambigu ; aucun accès n'est accordé.
        if len(ids_patients) != 1:
            return None
        patient = Patient.objects.select_for_update().filter(
            pk=ids_patients[0], id_etablissement_id=id_hopital
        ).first()
        if patient is None:
            return None

        # Un seul code actif par dossier : une nouvelle demande invalide l'ancien.
        CodeVerification.objects.filter(id_patient=patient, utilise=False).update(utilise=True)
        maintenant = timezone.now()
        valeur_code = f"{secrets.randbelow(1_000_000):06d}"
        code = CodeVerification.objects.create(
            code=valeur_code,
            date_generation=maintenant,
            date_expiration=maintenant + timedelta(minutes=5),
            id_patient=patient,
            id_etablissement_id=id_hopital,
        )
        return {"code": valeur_code, "id_patient": patient.pk, "id_code": code.pk}


@transaction.atomic
def verifier_code(*, id_hopital, numero_telephone, code):
    """Consomme atomiquement un code valide et retourne son dossier patient."""
    telephone = (numero_telephone or "").strip()
    valeur_code = (code or "").strip()
    maintenant = timezone.now()
    if not telephone or len(valeur_code) != 6 or not valeur_code.isdigit():
        raise PortailPatientError(MESSAGE_CODE_INVALIDE)
    if not Etablissement.objects.filter(
        pk=id_hopital,
        type_etablissement=Etablissement.TYPE_HOPITAL,
    ).exists():
        raise PortailPatientError(MESSAGE_CODE_INVALIDE)

    with temporary_tenant(id_hopital):
        ids_patients = list(
            Telephone.objects.filter(
                id_etablissement_id=id_hopital,
                numero_telephone=telephone,
            ).values_list("id_patient_id", flat=True).distinct()
        )
        if len(ids_patients) != 1:
            raise PortailPatientError(MESSAGE_CODE_INVALIDE)
        patient = Patient.objects.filter(pk=ids_patients[0], id_etablissement_id=id_hopital).first()
        if patient is None:
            raise PortailPatientError(MESSAGE_CODE_INVALIDE)
        verification = (
            CodeVerification.objects.select_for_update()
            .filter(
                id_patient=patient,
                id_etablissement_id=id_hopital,
                code=valeur_code,
                utilise=False,
                date_expiration__gt=maintenant,
            )
            .order_by("-date_generation")
            .first()
        )
        if verification is None:
            raise PortailPatientError(MESSAGE_CODE_INVALIDE)
        verification.utilise = True
        verification.save(update_fields=("utilise",))
        return patient


def patient_portail_connecte(*, session, id_hopital):
    """Retourne le patient lié à la session si le contexte RLS est cohérent."""
    patient_id = session.get("portail_patient_id")
    hopital_session = session.get("portail_hopital_id")
    if not patient_id or str(hopital_session) != str(id_hopital):
        raise PortailPatientError("La session du portail a expiré. Vérifiez à nouveau votre numéro.")
    if current_tenant() != str(id_hopital):
        raise PortailPatientError("Le contexte de sécurité du portail n'est pas valide.")
    try:
        return Patient.objects.get(pk=patient_id, id_etablissement_id=id_hopital)
    except Patient.DoesNotExist as exc:
        raise PortailPatientError("Le dossier patient de cette session n'est plus disponible.") from exc


def medecins_disponibles(*, id_hopital):
    if current_tenant() != str(id_hopital):
        raise PortailPatientError("Le contexte de sécurité du portail n'est pas valide.")
    return Medecin.objects.filter(
        matricule_personnel__id_etablissement_id=id_hopital,
        matricule_personnel__actif=True,
        matricule_personnel__role_metier="medecin",
    ).select_related("matricule_personnel").order_by(
        "matricule_personnel__nom", "matricule_personnel__prenom"
    )


@transaction.atomic
def prendre_rendez_vous(*, patient, id_hopital, matricule_medecin, date_rendez_vous, heure_rendez_vous):
    if current_tenant() != str(id_hopital) or str(patient.id_etablissement_id) != str(id_hopital):
        raise PortailPatientError("Le patient ne peut prendre rendez-vous que dans son hôpital.")
    maintenant = timezone.localtime(timezone.now())
    heure_locale = timezone.make_aware(
        datetime.combine(date_rendez_vous, heure_rendez_vous),
        timezone.get_current_timezone(),
    )
    if heure_locale <= maintenant:
        raise ValidationError({"date_rendez_vous": "Choisissez une date et une heure futures."})
    if not Medecin.objects.filter(
        pk=matricule_medecin,
        matricule_personnel__id_etablissement_id=id_hopital,
        matricule_personnel__actif=True,
    ).exists():
        raise ValidationError({"matricule_personnel": "Ce médecin n'exerce pas dans cet hôpital."})
    return RendezVous.objects.create(
        date_rendez_vous=date_rendez_vous,
        heure_rendez_vous=heure_rendez_vous,
        statut_rendez_vous=RendezVous.PLANIFIE,
        id_patient=patient,
        matricule_personnel_id=matricule_medecin,
        id_etablissement_id=id_hopital,
    )


@transaction.atomic
def annuler_rendez_vous_portail(*, rendez_vous, patient):
    if str(rendez_vous.id_patient_id) != str(patient.pk):
        raise PortailPatientError("Ce rendez-vous n'appartient pas à votre dossier.")
    try:
        return rendez_vous.annuler()
    except ValidationError:
        raise
