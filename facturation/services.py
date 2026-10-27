"""Génération et règlements de facture hospitalière (RG24-RG27)."""

from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.db.rls import current_tenant, temporary_tenant
from etablissements.models import Etablissement, JournalAction, Personnel, Pharmacie as PharmacieEtablissement
from facturation.models import Facture, LigneFacture, Paiement
from laboratoire.models import ExamenPrescrit
from pharmacie.models import LigneVente, Prescription, Vente
from soins.models import Acte, Consultation, Hospitalisation


class FacturationError(Exception):
    """Erreur de contexte ou de cohérence de facturation."""


def _verifier_hopital(id_hopital):
    if current_tenant() != str(id_hopital):
        raise FacturationError("La session doit être positionnée sur l'hôpital courant.")
    if not Etablissement.objects.filter(pk=id_hopital, type_etablissement=Etablissement.TYPE_HOPITAL).exists():
        raise FacturationError("La facturation est réservée à un hôpital.")


def _lignes_ventes_de_l_episode(*, consultation, id_hopital):
    """Lit sous RLS pharmacie uniquement les lignes livrées liées aux ordonnances de l'épisode."""
    prescriptions = list(
        Prescription.objects.filter(id_acte_consultation_id=consultation.pk).values_list("id_prescription", flat=True)
    )
    if not prescriptions:
        return []

    ids_pharmacies = list(
        PharmacieEtablissement.objects.filter(
            id_etablissement_hopital_rattachement_id=id_hopital
        ).values_list("id_etablissement_id", flat=True)
    )
    lignes_facturables = []
    for id_pharmacie in ids_pharmacies:
        with temporary_tenant(id_pharmacie):
            ventes = list(
                Vente.objects.filter(
                    id_etablissement_id=id_pharmacie,
                    id_patient_id=consultation.id_acte.id_patient_id,
                    id_prescription_id__in=prescriptions,
                ).values_list("id_vente", flat=True)
            )
            if not ventes:
                continue
            lignes = LigneVente.objects.filter(
                id_etablissement_id=id_pharmacie,
                id_vente_id__in=ventes,
                quantite_delivree__gt=0,
            ).values(
                "id_ligne_vente",
                "id_medicament__nom_medicament",
                "quantite_delivree",
                "prix_facture",
            )
            lignes_facturables.extend(
                {
                    "id_ligne_vente": ligne["id_ligne_vente"],
                    "designation": ligne["id_medicament__nom_medicament"],
                    "quantite": Decimal(ligne["quantite_delivree"]),
                    "prix_unitaire": ligne["prix_facture"],
                }
                for ligne in lignes
            )
    return lignes_facturables


@transaction.atomic
def generer_facture(*, id_hopital, id_acte_consultation, matricule_personnel):
    """Émet une facture unique à la clôture et rassemble actes + délivrances hospitalières."""
    _verifier_hopital(id_hopital)
    try:
        consultation = (
            Consultation.objects.select_for_update()
            .select_related("id_acte")
            .get(pk=id_acte_consultation)
        )
    except Consultation.DoesNotExist as exc:
        raise ValidationError({"id_acte_consultation": "Consultation introuvable dans cet hôpital."}) from exc
    if consultation.statut_episode != Consultation.CLOS:
        raise ValidationError({"id_acte_consultation": "La facture est émise à la clôture de l'épisode (RG25)."})
    if Facture.objects.filter(id_acte_consultation=consultation).exists():
        raise ValidationError({"id_acte_consultation": "Cet épisode possède déjà sa facture unique (RG25)."})

    try:
        auteur = Personnel.objects.get(pk=matricule_personnel)
    except Personnel.DoesNotExist as exc:
        raise ValidationError({"matricule_personnel": "Personnel de caisse introuvable."}) from exc
    if auteur.id_etablissement_id != id_hopital or auteur.role_metier not in ("comptable", "administrateur"):
        raise ValidationError("La facture doit être générée par un comptable ou administrateur de cet hôpital.")

    actes = {consultation.id_acte_id: consultation.id_acte}
    hospitalisations = Hospitalisation.objects.filter(id_acte_consultation=consultation).select_related("id_acte")
    for hospitalisation in hospitalisations:
        actes[hospitalisation.id_acte_id] = hospitalisation.id_acte
    examens_realises = ExamenPrescrit.objects.filter(
        id_acte_consultation=consultation,
        date_realisation__isnull=False,
    ).select_related("id_acte", "id_examen")
    for examen in examens_realises:
        actes[examen.id_acte_id] = examen.id_acte

    ventes = _lignes_ventes_de_l_episode(consultation=consultation, id_hopital=id_hopital)
    facture = Facture.objects.create(
        date_emission=timezone.localdate(),
        id_patient_id=consultation.id_acte.id_patient_id,
        id_acte_consultation=consultation,
        statut_facture=Facture.EMISE,
        id_etablissement_id=id_hopital,
    )
    for acte in actes.values():
        LigneFacture.objects.create(
            designation=acte.libelle_acte,
            quantite=Decimal("1.00"),
            prix_unitaire=acte.montant_base,
            montant_ligne=acte.montant_base,
            id_facture=facture,
            id_acte=acte,
            id_etablissement_id=id_hopital,
        )
    for ligne in ventes:
        montant = (ligne["quantite"] * ligne["prix_unitaire"]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        LigneFacture.objects.create(
            designation=ligne["designation"],
            quantite=ligne["quantite"],
            prix_unitaire=ligne["prix_unitaire"],
            montant_ligne=montant,
            id_facture=facture,
            id_ligne_vente_id=ligne["id_ligne_vente"],
            id_etablissement_id=id_hopital,
        )
    if facture.montant_patient == 0:
        facture.statut_facture = Facture.SOLDEE
        facture.save(update_fields=("statut_facture",))
    JournalAction.objects.create(
        type_action="facture_episode",
        details=f"Facture {facture.pk} émise pour l'épisode {consultation.pk}",
        matricule_personnel=auteur,
        id_etablissement_id=id_hopital,
    )
    return facture


@transaction.atomic
def enregistrer_paiement(*, id_hopital, id_facture, matricule_personnel, montant_paye, moyen_paiement=None):
    """Enregistre un règlement partiel ou total sans permettre le dépassement du solde patient (RG26-RG27)."""
    _verifier_hopital(id_hopital)
    try:
        facture = Facture.objects.select_for_update().get(pk=id_facture)
    except Facture.DoesNotExist as exc:
        raise ValidationError({"id_facture": "Facture introuvable dans cet hôpital."}) from exc
    try:
        personnel = Personnel.objects.get(pk=matricule_personnel)
    except Personnel.DoesNotExist as exc:
        raise ValidationError({"matricule_personnel": "Personnel de caisse introuvable."}) from exc
    if personnel.id_etablissement_id != id_hopital or personnel.role_metier not in ("comptable", "administrateur"):
        raise ValidationError("Le paiement doit être enregistré par un comptable ou administrateur de cet hôpital.")
    try:
        montant = Decimal(montant_paye).quantize(Decimal("0.01"))
    except Exception as exc:
        raise ValidationError({"montant_paye": "Saisissez un montant valide."}) from exc
    if montant <= 0:
        raise ValidationError({"montant_paye": "Le montant payé doit être strictement positif."})
    if moyen_paiement and moyen_paiement not in dict(Paiement.MOYEN_CHOICES):
        raise ValidationError({"moyen_paiement": "Moyen de paiement inconnu."})
    if montant > facture.solde_patient:
        raise ValidationError({"montant_paye": f"Le montant dépasse le solde restant ({facture.solde_patient})."})

    paiement = Paiement.objects.create(
        montant_paye=montant,
        date_paiement=timezone.localdate(),
        moyen_paiement=moyen_paiement,
        id_facture=facture,
        matricule_personnel=personnel,
        id_etablissement_id=id_hopital,
    )
    facture.statut_facture = Facture.SOLDEE if facture.solde_patient == 0 else Facture.PARTIELLEMENT_PAYEE
    facture.save(update_fields=("statut_facture",))
    JournalAction.objects.create(
        type_action="paiement_facture",
        details=f"Paiement {paiement.pk} enregistré pour la facture {facture.pk}",
        matricule_personnel=personnel,
        id_etablissement_id=id_hopital,
    )
    return paiement
