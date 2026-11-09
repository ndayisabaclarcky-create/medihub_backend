"""Génération temporaire de PDF patients sans fichier public sur le serveur."""

from io import BytesIO
from textwrap import wrap

from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework.response import Response

from facturation.models import Facture
from laboratoire.models import ResultatExamen
from pharmacie.models import Prescription
from patients.models import DocumentMedicalPartage
from portail_patient.models import AccesDocumentPatient


LABELS = {
    AccesDocumentPatient.RESULTAT: "Résultat d'examen",
    AccesDocumentPatient.PRESCRIPTION: "Prescription médicale",
    AccesDocumentPatient.FACTURE: "Facture hospitalière",
}


def _pdf_string(value):
    """Encode une chaîne en littéral PDF WinAnsi, en échappant les caractères spéciaux."""
    raw = str(value).encode("cp1252", errors="replace")
    result = []
    for byte in raw:
        if byte in (ord("("), ord(")"), ord("\\")):
            result.append("\\" + chr(byte))
        elif byte < 32 or byte > 126:
            result.append(f"\\{byte:03o}")
        else:
            result.append(chr(byte))
    return "".join(result)


def generer_pdf(titre, lignes):
    """Produit un PDF texte minimal en WinAnsi sans dépendance de rendu externe."""
    lignes_page = []
    for ligne in lignes:
        lignes_page.extend(wrap(str(ligne), width=88, replace_whitespace=True, drop_whitespace=True) or [""])
    pages = [lignes_page[index:index + 47] for index in range(0, len(lignes_page), 47)] or [[]]

    objets = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    }
    references_pages = []
    for index, contenu in enumerate(pages):
        page_id = 5 + index * 2
        flux_id = page_id + 1
        references_pages.append(f"{page_id} 0 R")
        commandes = ["BT", "/F2 16 Tf", "50 790 Td", f"({_pdf_string(titre)}) Tj", "/F1 10 Tf", "0 -28 Td"]
        for ligne in contenu:
            commandes.extend((f"({_pdf_string(ligne)}) Tj", "0 -15 Td"))
        commandes.append("ET")
        flux = "\n".join(commandes).encode("ascii")
        objets[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {flux_id} 0 R >>"
        ).encode("ascii")
        objets[flux_id] = f"<< /Length {len(flux)} >>\nstream\n".encode("ascii") + flux + b"\nendstream"

    objets[2] = f"<< /Type /Pages /Kids [{' '.join(references_pages)}] /Count {len(pages)} >>".encode("ascii")
    sortie = bytearray(b"%PDF-1.4\n% MediHub\n")
    decalages = [0] * (max(objets) + 1)
    for identifiant in sorted(objets):
        decalages[identifiant] = len(sortie)
        sortie.extend(f"{identifiant} 0 obj\n".encode("ascii"))
        sortie.extend(objets[identifiant])
        sortie.extend(b"\nendobj\n")
    debut_xref = len(sortie)
    sortie.extend(f"xref\n0 {len(decalages)}\n".encode("ascii"))
    sortie.extend(b"0000000000 65535 f \n")
    for decalage in decalages[1:]:
        sortie.extend(f"{decalage:010d} 00000 n \n".encode("ascii"))
    sortie.extend(
        f"trailer\n<< /Size {len(decalages)} /Root 1 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(sortie)


def _nom_patient(patient):
    return f"{patient.prenom_patient} {patient.nom_patient}"


def _document(type_document, id_document, patient, tenant):
    if type_document == AccesDocumentPatient.HISTORIQUE_PARTAGE:
        try:
            obj = DocumentMedicalPartage.objects.get(
                pk=id_document,
                id_etablissement_id=tenant,
                historique__id_patient_destination=patient,
            )
        except DocumentMedicalPartage.DoesNotExist as exc:
            raise Http404 from exc
        return obj, []

    if type_document == AccesDocumentPatient.RESULTAT:
        try:
            obj = ResultatExamen.objects.select_related(
                "id_acte_examen_prescrit__id_examen", "id_acte_examen_prescrit__id_acte__id_patient"
            ).get(
                pk=id_document,
                id_etablissement_id=tenant,
                id_acte_examen_prescrit__id_acte__id_patient=patient,
            )
        except ResultatExamen.DoesNotExist as exc:
            raise Http404 from exc
        examen = obj.id_acte_examen_prescrit.id_examen.libelle_examen
        return obj, [
            f"Patient : {_nom_patient(patient)}",
            f"Établissement : {patient.id_etablissement.nom_etablissement}",
            f"Examen : {examen}",
            f"Date de disponibilité : {obj.date_disponibilite or 'Non renseignée'}",
            "",
            "Résultat :",
            obj.contenu_resultat or "Aucun contenu détaillé n'a été saisi.",
        ]

    if type_document == AccesDocumentPatient.PRESCRIPTION:
        try:
            obj = Prescription.objects.select_related("matricule_personnel").prefetch_related(
                "lignes__id_medicament"
            ).get(pk=id_document, id_etablissement_id=tenant, id_patient=patient)
        except Prescription.DoesNotExist as exc:
            raise Http404 from exc
        lignes = [
            f"Patient : {_nom_patient(patient)}",
            f"Établissement : {patient.id_etablissement.nom_etablissement}",
            f"Date : {obj.date_prescription}",
            f"Médecin : {obj.matricule_personnel.matricule_personnel.prenom} "
            f"{obj.matricule_personnel.matricule_personnel.nom}",
            "",
            "Médicaments prescrits :",
        ]
        lignes.extend(
            f"- {ligne.id_medicament.nom_medicament} {ligne.id_medicament.dosage} : {ligne.posologie}; "
            f"quantité {ligne.quantite_prescrite}; durée {ligne.duree_traitement} jour(s)"
            for ligne in obj.lignes.all()
        )
        return obj, lignes

    if type_document == AccesDocumentPatient.FACTURE:
        try:
            obj = Facture.objects.select_related("id_patient").prefetch_related("lignes", "paiements").get(
                pk=id_document, id_etablissement_id=tenant, id_patient=patient
            )
        except Facture.DoesNotExist as exc:
            raise Http404 from exc
        lignes = [
            f"Patient : {_nom_patient(patient)}",
            f"Établissement : {patient.id_etablissement.nom_etablissement}",
            f"Date d'émission : {obj.date_emission}",
            f"Statut : {obj.get_statut_facture_display()}",
            "",
            "Détail :",
        ]
        lignes.extend(
            f"- {ligne.designation} — {ligne.quantite} x {ligne.prix_unitaire} = {ligne.montant_ligne} FBU"
            for ligne in obj.lignes.all()
        )
        lignes.extend(
            (
                "",
                f"Total : {obj.montant_total} FBU",
                f"Part assurance : {obj.montant_assurance} FBU",
                f"Part patient : {obj.montant_patient} FBU",
                f"Déjà payé : {obj.total_paye} FBU",
                f"Solde : {obj.solde_patient} FBU",
            )
        )
        return obj, lignes

    raise Http404


def lister_documents(patient):
    tenant = patient.id_etablissement_id
    documents = []
    resultats = ResultatExamen.objects.filter(
        id_etablissement_id=tenant,
        id_acte_examen_prescrit__id_acte__id_patient=patient,
    ).select_related("id_acte_examen_prescrit__id_examen")
    documents.extend(
        {
            "type_document": AccesDocumentPatient.RESULTAT,
            "id_document": str(obj.pk),
            "titre": obj.id_acte_examen_prescrit.id_examen.libelle_examen,
            "date": obj.date_disponibilite,
        }
        for obj in resultats
    )
    prescriptions = Prescription.objects.filter(id_etablissement_id=tenant, id_patient=patient)
    documents.extend(
        {
            "type_document": AccesDocumentPatient.PRESCRIPTION,
            "id_document": str(obj.pk),
            "titre": f"Prescription du {obj.date_prescription}",
            "date": obj.date_prescription,
        }
        for obj in prescriptions
    )
    factures = Facture.objects.filter(id_etablissement_id=tenant, id_patient=patient)
    documents.extend(
        {
            "type_document": AccesDocumentPatient.FACTURE,
            "id_document": str(obj.pk),
            "titre": f"Facture du {obj.date_emission}",
            "date": obj.date_emission,
        }
        for obj in factures
    )
    documents.extend(
        {
            "type_document": AccesDocumentPatient.HISTORIQUE_PARTAGE,
            "id_document": str(obj.pk),
            "titre": obj.titre,
            "date": obj.date_document,
            "id_hopital_source": str(obj.historique.id_etablissement_source),
        }
        for obj in DocumentMedicalPartage.objects.filter(
            id_etablissement_id=tenant,
            historique__id_patient_destination=patient,
        ).select_related("historique")
    )
    return sorted(documents, key=lambda item: (item["date"] or timezone.localdate(), item["titre"]), reverse=True)


def reponse_document(*, patient, type_document, id_document, telecharger):
    if type_document not in LABELS:
        raise Http404
    objet, lignes = _document(type_document, id_document, patient, patient.id_etablissement_id)
    AccesDocumentPatient.objects.create(
        id_patient=patient,
        id_etablissement_id=patient.id_etablissement_id,
        type_document=type_document,
        id_document=id_document,
        action=AccesDocumentPatient.TELECHARGEMENT if telecharger else AccesDocumentPatient.CONSULTATION,
    )
    contenu = bytes(objet.contenu_pdf) if type_document == AccesDocumentPatient.HISTORIQUE_PARTAGE else generer_pdf(LABELS[type_document], lignes)
    nom = f"medihub-{type_document}-{id_document}.pdf"
    response = FileResponse(
        BytesIO(contenu),
        content_type="application/pdf",
        as_attachment=telecharger,
        filename=nom,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    return response
