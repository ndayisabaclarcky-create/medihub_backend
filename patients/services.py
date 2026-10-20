"""
Rapprochement inter-hôpitaux et partage consenti des allergies / antécédents
(RG35, RG36, RG37 — Processus 3 du cahier des charges).

C'est le SEUL endroit du code autorisé à franchir l'isolation entre
établissements (via core.db.rls.temporary_tenant). Tout passage de ce type doit
rester ici, pour qu'il soit auditable en un seul fichier.
"""

from django.db import IntegrityError, transaction

from core.db.rls import current_tenant, temporary_tenant
from patients.models import IndexRapprochement, PartageDossier, Patient


class PartageDossierError(Exception):
    """Le partage ne peut pas être effectué (message destiné à l'utilisateur)."""


class PartageDejaEffectue(PartageDossierError):
    """RG36 : les allergies/antécédents ne se copient qu'une seule fois."""


def rechercher_correspondances(patient):
    """
    Cherche dans l'index les entrées des AUTRES établissements portant le même
    numéro de pièce d'identité. Ne renvoie que des lignes d'index (numéro,
    id_patient, id_etablissement) : aucune donnée médicale, aucun nom.

    Fonctionne grâce à la policy FOR SELECT ouverte sur index_rapprochement
    (migration patients.0004).
    """
    numero = patient.numero_piece_identite
    if not numero:
        return []
    return list(
        IndexRapprochement.objects.filter(numero_piece_identite=numero)
        .exclude(id_etablissement=patient.id_etablissement_id)
        .select_related("id_etablissement")
    )


def partager_dossier(*, patient_destination, id_patient_source, personnel):
    """
    RG36-RG37 : copie UNE SEULE FOIS les allergies et antécédents médicaux du
    patient `id_patient_source` (autre hôpital) vers `patient_destination`
    (nouveau dossier de l'hôpital courant), et trace le consentement
    (date, patients, membre du personnel qui l'a recueilli).

    `personnel` est le membre du personnel ayant recueilli le consentement oral.
    À appeler avec la session PostgreSQL positionnée sur l'établissement du
    destinataire (ce que fait EtablissementContextMiddleware).

    Mécanisme : seule la lecture des deux champs du patient source se fait avec
    le contexte basculé sur l'hôpital source (SET LOCAL via temporary_tenant),
    puis le contexte d'origine est restauré avant toute écriture. Aucune autre
    donnée du dossier source n'est lue.
    """
    with transaction.atomic():
        id_etab_dest = str(patient_destination.id_etablissement_id)

        # 1. Garde-fous sur le contexte et les acteurs.
        if current_tenant() != id_etab_dest:
            raise PartageDossierError(
                "La session n'est pas positionnée sur l'établissement du patient destinataire."
            )
        if str(personnel.id_etablissement_id) != id_etab_dest:
            raise PartageDossierError(
                "Le consentement doit être recueilli par un membre du personnel de l'hôpital destinataire."
            )
        if not patient_destination.numero_piece_identite:
            raise PartageDossierError("Le patient destinataire n'a pas de numéro de pièce d'identité (RG35).")

        # 2. RG36 « une seule fois » + dossier destinataire neuf.
        if PartageDossier.objects.filter(id_patient_destination=patient_destination).exists():
            raise PartageDejaEffectue("Ce dossier a déjà reçu un partage d'allergies et d'antécédents.")
        if patient_destination.allergies or patient_destination.antecedents_medicaux:
            raise PartageDossierError(
                "Le dossier destinataire contient déjà des allergies ou antécédents : "
                "le partage ne s'applique qu'à un nouveau dossier."
            )

        # 3. La correspondance doit exister dans l'index, dans un AUTRE hôpital.
        entree = next(
            (e for e in rechercher_correspondances(patient_destination) if e.id_patient_id == id_patient_source),
            None,
        )
        if entree is None:
            raise PartageDossierError("Aucune correspondance dans l'index pour ce patient source.")

        # 4. Seul passage au-dessus de l'isolation : lecture de DEUX colonnes.
        with temporary_tenant(entree.id_etablissement_id):
            donnees = (
                Patient.objects.filter(pk=entree.id_patient_id)
                .values_list("allergies", "antecedents_medicaux")
                .first()
            )
        if donnees is None:
            raise PartageDossierError("Dossier source introuvable.")
        allergies, antecedents = donnees

        # 5. Écritures, avec le contexte du destinataire restauré.
        patient_destination.allergies = allergies
        patient_destination.antecedents_medicaux = antecedents
        patient_destination.save()
        try:
            with transaction.atomic():
                return PartageDossier.objects.create(
                    id_patient_source_id=entree.id_patient_id,
                    id_patient_destination=patient_destination,
                    matricule_personnel=personnel,
                )
        except IntegrityError as exc:  # garantie en base (course entre deux requêtes)
            raise PartageDejaEffectue("Ce dossier a déjà reçu un partage d'allergies et d'antécédents.") from exc
