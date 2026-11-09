"""Partage consenti d'un résumé et de documents entre dossiers hospitaliers."""

from datetime import datetime

from django.db import transaction
from django.http import Http404

from core.db.rls import temporary_tenant
from etablissements.models import Etablissement
from patients.models import DocumentMedicalPartage, HistoriqueMedicalPartage, Patient
from portail_patient.documents import LABELS, _document, generer_pdf, lister_documents
from portail_patient.models import AccesDocumentPatient


class PartageHistoriqueError(Exception):
    pass


@transaction.atomic
def partager_historique_patient(*, compte, id_hopital_source, id_hopital_destination, documents):
    if not compte.telephone_verifie or not compte.actif:
        raise PartageHistoriqueError("Le compte patient doit être activé et son téléphone vérifié.")
    if str(id_hopital_source) == str(id_hopital_destination):
        raise PartageHistoriqueError("Le partage doit viser un autre hôpital.")
    hopital_source = Etablissement.objects.filter(
        pk=id_hopital_source, type_etablissement=Etablissement.TYPE_HOPITAL
    ).first()
    hopital_destination = Etablissement.objects.filter(
        pk=id_hopital_destination, type_etablissement=Etablissement.TYPE_HOPITAL
    ).first()
    if not hopital_source or not hopital_destination:
        raise PartageHistoriqueError("Un des hôpitaux sélectionnés est introuvable.")

    with temporary_tenant(hopital_source.pk):
        patient_source = Patient.objects.filter(
            compte_patient=compte, id_etablissement_id=hopital_source.pk
        ).prefetch_related("mesures_poids").first()
        if patient_source is None:
            raise PartageHistoriqueError("Aucun dossier source MediHub n'est lié à ce compte dans cet hôpital.")
        resume = {
            "nom": patient_source.nom_patient,
            "prenom": patient_source.prenom_patient,
            "date_naissance": patient_source.date_naissance.isoformat(),
            "allergies": patient_source.allergies,
            "antecedents_medicaux": patient_source.antecedents_medicaux,
            "groupe_sanguin": patient_source.groupe_sanguin,
            "informations_declarees_par_patient": {
                "allergies": compte.allergies_declarees,
                "antecedents": compte.antecedents_declares,
                "groupe_sanguin": compte.groupe_sanguin_declare,
            },
            "mesures_poids": [
                {"poids_kg": str(mesure.poids_kg), "date_mesure": mesure.date_mesure.isoformat()}
                for mesure in patient_source.mesures_poids.all()
            ],
            "hopital_source": hopital_source.nom_etablissement,
        }
        documents_source = {
            (item["type_document"], item["id_document"]): item
            for item in lister_documents(patient_source)
        }
        copies = []
        total_octets = 0
        for selection in documents:
            type_document = selection["type_document"]
            id_document = selection["id_document"]
            item = documents_source.get((type_document, str(id_document)))
            if item is None:
                raise PartageHistoriqueError("Un document sélectionné n'appartient pas à votre dossier source.")
            try:
                obj, lignes = _document(type_document, id_document, patient_source, hopital_source.pk)
            except Http404 as exc:
                raise PartageHistoriqueError("Un document sélectionné n'est plus disponible.") from exc
            contenu = generer_pdf(LABELS[type_document], lignes)
            total_octets += len(contenu)
            if len(contenu) > 2 * 1024 * 1024 or total_octets > 8 * 1024 * 1024:
                raise PartageHistoriqueError("La taille totale des documents sélectionnés dépasse la limite de 8 Mo.")
            date_document = item["date"]
            if isinstance(date_document, datetime):
                date_document = date_document.date()
            copies.append({
                "type_document_source": type_document,
                "id_document_source": id_document,
                "titre": item["titre"][:150],
                "date_document": date_document,
                "contenu_pdf": contenu,
            })

    with temporary_tenant(hopital_destination.pk):
        patient_destination = Patient.objects.filter(
            compte_patient=compte, id_etablissement_id=hopital_destination.pk
        ).first()
        if patient_destination is None:
            raise PartageHistoriqueError(
                "Prenez d'abord rendez-vous dans l'hôpital destinataire pour y créer votre dossier local."
            )
        historique = HistoriqueMedicalPartage.objects.create(
            id_compte_patient=compte,
            id_patient_source=patient_source.pk,
            id_etablissement_source=hopital_source.pk,
            id_patient_destination=patient_destination,
            id_etablissement_id=hopital_destination.pk,
            resume_medical=resume,
        )
        for copie in copies:
            DocumentMedicalPartage.objects.create(
                historique=historique,
                id_etablissement_id=hopital_destination.pk,
                **copie,
            )
    return historique
