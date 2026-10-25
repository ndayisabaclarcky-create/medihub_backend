"""Operations métier du Bloc 4 et seul accès pharmacie aux prescriptions inter-tenant."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.db.rls import current_tenant, temporary_tenant
from etablissements.models import (
    Etablissement,
    JournalAction,
    Personnel,
    Pharmacie as PharmacieEtablissement,
)
from patients.models import Client
from pharmacie.models import (
    LignePrescription,
    LigneVente,
    LotMedicament,
    Medicament,
    Prescription,
    Vente,
)


class PharmacieError(Exception):
    """Opération de délivrance impossible selon les règles métier."""


def _pharmacie_courante(id_pharmacie):
    if current_tenant() != str(id_pharmacie):
        raise PharmacieError("La session PostgreSQL doit être positionnée sur la pharmacie concernée.")
    try:
        pharmacie = PharmacieEtablissement.objects.select_related(
            "id_etablissement", "id_etablissement_hopital_rattachement"
        ).get(pk=id_pharmacie)
    except PharmacieEtablissement.DoesNotExist as exc:
        raise PharmacieError("La pharmacie est introuvable.") from exc
    if pharmacie.id_etablissement.type_etablissement != Etablissement.TYPE_PHARMACIE:
        raise PharmacieError("L'établissement courant n'est pas une pharmacie.")
    return pharmacie


def _enregistrer_ou_maj_client(*, id_pharmacie, informations):
    nom = (informations.get("nom") or "").strip()
    prenom = (informations.get("prenom") or "").strip() or None
    telephone = (informations.get("telephone_contact") or "").strip() or None
    if not nom:
        raise ValidationError({"client": "Le nom du client est obligatoire en pharmacie indépendante (RG31)."})

    clients = Client.objects.filter(id_etablissement_id=id_pharmacie)
    if telephone:
        client = clients.filter(telephone_contact=telephone).order_by("id_client").first()
    else:
        client = clients.filter(nom__iexact=nom).filter(
            Q(prenom__iexact=prenom) if prenom else (Q(prenom__isnull=True) | Q(prenom=""))
        ).order_by("id_client").first()

    if client is None:
        return Client.objects.create(
            nom=nom,
            prenom=prenom,
            telephone_contact=telephone,
            id_etablissement_id=id_pharmacie,
        )

    client.nom = nom
    client.prenom = prenom
    client.telephone_contact = telephone
    client.save()
    return client


def _prescription_et_lignes_hospitalieres(*, pharmacie, id_prescription, id_patient):
    id_hopital = pharmacie.id_etablissement_hopital_rattachement_id
    if not id_hopital:
        raise ValidationError("Une pharmacie indépendante ne peut utiliser qu'une prescription externe.")

    with temporary_tenant(id_hopital):
        prescription = (
            Prescription.objects.select_for_update()
            .filter(pk=id_prescription, id_etablissement_id=id_hopital)
            .values("id_prescription", "id_patient_id", "id_etablissement_id")
            .first()
        )
        if prescription is None:
            raise ValidationError({"id_prescription": "Prescription interne introuvable dans l'hôpital rattaché."})
        if str(prescription["id_patient_id"]) != str(id_patient):
            raise ValidationError({"id_patient": "La prescription concerne un autre patient."})
        lignes = list(
            LignePrescription.objects.filter(
                id_prescription_id=id_prescription,
                id_etablissement_id=id_hopital,
            ).values("id_medicament__code_medicament", "quantite_prescrite")
        )
    if not lignes:
        raise ValidationError({"id_prescription": "La prescription ne contient aucun médicament."})
    return {
        ligne["id_medicament__code_medicament"]: ligne["quantite_prescrite"] for ligne in lignes
    }


def consulter_prescription_hospitaliere(*, id_pharmacie, id_prescription):
    """Expose à la pharmacie rattachée le strict nécessaire à une délivrance."""
    pharmacie = _pharmacie_courante(id_pharmacie)
    id_hopital = pharmacie.id_etablissement_hopital_rattachement_id
    if not id_hopital:
        raise ValidationError("Une pharmacie indépendante ne peut consulter que des prescriptions externes.")

    with temporary_tenant(id_hopital):
        prescription = (
            Prescription.objects.filter(pk=id_prescription, id_etablissement_id=id_hopital)
            .values("id_prescription", "id_patient_id", "date_prescription")
            .first()
        )
        if prescription is None:
            raise ValidationError({"id_prescription": "Prescription interne introuvable dans l'hôpital rattaché."})
        lignes = list(
            LignePrescription.objects.filter(
                id_prescription_id=id_prescription,
                id_etablissement_id=id_hopital,
            ).values(
                "id_medicament__code_medicament",
                "id_medicament__nom_medicament",
                "id_medicament__dosage",
                "posologie",
                "quantite_prescrite",
                "duree_traitement",
            )
        )

    # De retour dans le contexte de la pharmacie : on vérifie, par code_medicament, quels
    # médicaments prescrits existent dans SON catalogue (aucun catalogue n'est partagé, RG34).
    codes_du_catalogue = set(
        Medicament.objects.filter(
            id_etablissement_id=id_pharmacie,
            code_medicament__in=[ligne["id_medicament__code_medicament"] for ligne in lignes],
        ).values_list("code_medicament", flat=True)
    )

    return {
        "id_prescription": prescription["id_prescription"],
        "id_patient": prescription["id_patient_id"],
        "date_prescription": prescription["date_prescription"],
        "lignes": [
            {
                "code_medicament": ligne["id_medicament__code_medicament"],
                "disponible_dans_cette_pharmacie": ligne["id_medicament__code_medicament"] in codes_du_catalogue,
                "nom_medicament": ligne["id_medicament__nom_medicament"],
                "dosage": ligne["id_medicament__dosage"],
                "posologie": ligne["posologie"],
                "quantite_prescrite": ligne["quantite_prescrite"],
                "duree_traitement": ligne["duree_traitement"],
            }
            for ligne in lignes
        ],
    }


def _quantites_deja_delivrees(*, id_prescription, id_hopital):
    """Cumule les délivrances dans toutes les pharmacies de l'hôpital prescripteur."""
    resultat = {}
    pharmacies = PharmacieEtablissement.objects.filter(
        id_etablissement_hopital_rattachement_id=id_hopital
    ).values_list("id_etablissement_id", flat=True)
    for id_pharmacie in pharmacies:
        with temporary_tenant(id_pharmacie):
            lignes = (
                LigneVente.objects.filter(
                    id_etablissement_id=id_pharmacie,
                    id_vente__id_prescription_id=id_prescription,
                )
                .values("id_medicament__code_medicament")
                .annotate(total=Sum("quantite_delivree"))
            )
            for ligne in lignes:
                code = ligne["id_medicament__code_medicament"]
                resultat[code] = resultat.get(code, 0) + (ligne["total"] or 0)
    return resultat


def _preparer_lignes(*, id_pharmacie, prescriptions, quantites):
    if not quantites:
        raise ValidationError({"lignes": "Ajoutez au moins un médicament à la vente."})

    ids = [str(ligne["id_medicament"]) for ligne in quantites]
    if len(ids) != len(set(ids)):
        raise ValidationError({"lignes": "Un médicament ne peut apparaître qu'une fois dans la demande."})

    medicaments = {
        str(m.id_medicament): m
        for m in Medicament.objects.filter(id_etablissement_id=id_pharmacie, id_medicament__in=ids)
    }
    if len(medicaments) != len(ids):
        raise ValidationError({"lignes": "Un médicament demandé n'appartient pas au catalogue de cette pharmacie."})

    deja_delivrees = (
        _quantites_deja_delivrees(id_prescription=prescriptions["id"], id_hopital=prescriptions["id_hopital"])
        if prescriptions.get("interne")
        else {}
    )
    resultat = []
    for ligne in quantites:
        medicament = medicaments[str(ligne["id_medicament"])]
        try:
            valeur = ligne["quantite"]
            quantite = int(valeur)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"lignes": "Les quantités doivent être des entiers positifs."}) from exc
        if isinstance(valeur, float) and not valeur.is_integer():
            raise ValidationError({"lignes": "Les quantités doivent être des entiers positifs."})
        if quantite <= 0:
            raise ValidationError({"lignes": "Les quantités doivent être des entiers positifs."})

        if not medicament.vente_libre:
            if not prescriptions.get("interne") and not (
                prescriptions.get("prescripteur_externe")
                and prescriptions.get("date_prescription_externe")
            ):
                raise ValidationError(
                    {"id_prescription": f"{medicament.nom_medicament} exige une prescription et sa date (RG19-b, RG38)."}
                )

        if prescriptions.get("interne"):
            quantite_prescrite = prescriptions["codes"].get(medicament.code_medicament)
            if quantite_prescrite is None:
                raise ValidationError({"lignes": f"{medicament.nom_medicament} ne figure pas sur la prescription."})
            reste = quantite_prescrite - deja_delivrees.get(medicament.code_medicament, 0)
            if quantite > reste:
                raise ValidationError(
                    {"lignes": f"La quantité demandée dépasse le solde prescrit pour {medicament.nom_medicament}."}
                )
        resultat.append((medicament, quantite))
    return resultat


def _delivrer_depuis_lots(*, vente, medicament, quantite_demandee, id_pharmacie):
    aujourd_hui = timezone.localdate()
    lots = list(
        LotMedicament.objects.select_for_update()
        .filter(
            id_etablissement_id=id_pharmacie,
            id_medicament=medicament,
            date_peremption__gte=aujourd_hui,
            quantite_stock__gt=0,
        )
        .order_by("date_peremption", "numero_lot", "id_lot")
    )
    stock_total = sum(lot.quantite_stock for lot in lots)
    if stock_total == 0:
        raise ValidationError({"lignes": f"Aucun lot non périmé en stock pour {medicament.nom_medicament}."})

    a_delivrer = min(quantite_demandee, stock_total)
    segments = []
    reste = a_delivrer
    for lot in lots:
        quantite = min(reste, lot.quantite_stock)
        if quantite:
            segments.append((lot, quantite))
            reste -= quantite
        if reste == 0:
            break

    # La demande totale est ventilée entre les lignes par lot. Si le stock est
    # insuffisant, le reliquat demandé est porté par la dernière ligne (RG18).
    demandes = [quantite for _, quantite in segments]
    if stock_total < quantite_demandee:
        demandes[-1] += quantite_demandee - stock_total

    for (lot, quantite), quantite_demandee_lot in zip(segments, demandes):
        lot.quantite_stock -= quantite
        lot.save(update_fields=["quantite_stock"])
        LigneVente.objects.create(
            id_vente=vente,
            id_medicament=medicament,
            id_lot=lot,
            quantite_demandee=quantite_demandee_lot,
            quantite_delivree=quantite,
            prix_facture=medicament.prix_catalogue,
            id_etablissement_id=id_pharmacie,
        )
    return a_delivrer


@transaction.atomic
def enregistrer_vente(
    *,
    id_pharmacie,
    matricule_personnel,
    lignes,
    client=None,
    id_patient=None,
    id_prescription=None,
    nom_prescripteur_externe=None,
    date_prescription_externe=None,
    moyen_paiement=None,
    statut_paiement=None,
):
    """Crée une vente et délivre le stock disponible selon RG18-RG40.

    `lignes` est une liste de dictionnaires `{id_medicament, quantite}`.
    Pour une pharmacie rattachée, la prescription et le patient sont lus sous
    le contexte RLS de l'hôpital, uniquement afin de vérifier la délivrance.
    Pour une pharmacie indépendante, une fiche client est créée ou actualisée.
    """
    pharmacie = _pharmacie_courante(id_pharmacie)
    try:
        personnel = Personnel.objects.get(pk=matricule_personnel)
    except Personnel.DoesNotExist as exc:
        raise ValidationError({"matricule_personnel": "Le membre du personnel est introuvable."}) from exc
    if personnel.role_metier != "pharmacien" or str(personnel.id_etablissement_id) != str(id_pharmacie):
        raise ValidationError({"matricule_personnel": "La vente doit être enregistrée par un pharmacien de cette pharmacie."})

    interne = bool(pharmacie.id_etablissement_hopital_rattachement_id)
    codes_prescrits = {}
    if interne:
        if nom_prescripteur_externe or date_prescription_externe:
            raise ValidationError("Une vente interne ne peut pas contenir de prescription externe.")
        if client is not None:
            raise ValidationError("Une vente de pharmacie hospitalière est rattachée au patient, pas à un client.")
        if not id_patient or not id_prescription:
            raise ValidationError("En pharmacie hospitalière, patient et prescription sont obligatoires (RG19-a).")
        codes_prescrits = _prescription_et_lignes_hospitalieres(
            pharmacie=pharmacie,
            id_prescription=id_prescription,
            id_patient=id_patient,
        )
        informations_prescription = {
            "id": id_prescription,
            "id_hopital": pharmacie.id_etablissement_hopital_rattachement_id,
            "interne": True,
            "codes": codes_prescrits,
            "prescripteur_externe": None,
        }
        id_client = None
    else:
        if id_patient or id_prescription:
            raise ValidationError("Une pharmacie indépendante utilise une fiche client et une prescription externe.")
        if statut_paiement == Vente.ANNULE:
            raise ValidationError("Une vente ne peut pas être créée avec le statut annulé.")
        # Décision D5 : l'encaissement se fait au comptoir, la vente est donc enregistrée comme payée.
        if not moyen_paiement:
            raise ValidationError(
                {"moyen_paiement": "Le moyen de paiement est obligatoire (espèces, mobile money ou carte)."}
            )
        statut_paiement = Vente.PAYE
        if not isinstance(client, dict):
            raise ValidationError({"client": "Les informations du client sont requises (RG31)."})
        client_obj = _enregistrer_ou_maj_client(id_pharmacie=id_pharmacie, informations=client)
        id_client = client_obj.id_client
        informations_prescription = {
            "id": None,
            "interne": False,
            "codes": {},
            "prescripteur_externe": (nom_prescripteur_externe or "").strip() or None,
            "date_prescription_externe": date_prescription_externe,
        }

    items = _preparer_lignes(
        id_pharmacie=id_pharmacie,
        prescriptions=informations_prescription,
        quantites=lignes,
    )

    vente = Vente(
        date_vente=timezone.now(),
        id_patient_id=id_patient,
        id_client_id=id_client,
        id_prescription_id=id_prescription,
        nom_prescripteur_externe=(nom_prescripteur_externe or "").strip() or None,
        date_prescription_externe=date_prescription_externe,
        statut_paiement=statut_paiement,
        moyen_paiement=moyen_paiement,
        matricule_personnel=personnel,
        id_etablissement_id=id_pharmacie,
    )
    # Patient et prescription peuvent appartenir à l'hôpital rattaché ; leur
    # existence/concordance a été vérifiée explicitement sous son contexte RLS.
    # Vente.save() exécute la validation du modèle (sans ces deux champs).
    vente.save(force_insert=True)

    livrees = {}
    for medicament, quantite in items:
        livrees[medicament.code_medicament] = _delivrer_depuis_lots(
            vente=vente,
            medicament=medicament,
            quantite_demandee=quantite,
            id_pharmacie=id_pharmacie,
        )
    JournalAction.objects.create(
        type_action="vente_pharmacie",
        details=f"Vente {vente.id_vente} enregistrée",
        matricule_personnel=personnel,
        id_etablissement_id=id_pharmacie,
    )
    return vente, livrees


@transaction.atomic
def rediger_prescription(*, id_hopital, matricule_medecin, id_patient, id_consultation, lignes, date_prescription=None):
    """Crée une prescription interne complète avec au moins une ligne (RG15-RG16)."""
    if current_tenant() != str(id_hopital):
        raise PharmacieError("La session PostgreSQL doit être positionnée sur l'hôpital prescripteur.")
    if not lignes:
        raise ValidationError({"lignes": "Une prescription doit contenir au moins un médicament."})
    date_prescription = date_prescription or timezone.localdate()
    prescription = Prescription.objects.create(
        date_prescription=date_prescription,
        matricule_personnel_id=matricule_medecin,
        id_patient_id=id_patient,
        id_acte_consultation_id=id_consultation,
        id_etablissement_id=id_hopital,
    )
    ids = [str(ligne["id_medicament"]) for ligne in lignes]
    if len(ids) != len(set(ids)):
        raise ValidationError({"lignes": "Un médicament ne peut apparaître qu'une fois sur une prescription."})
    medicaments = {
        str(m.id_medicament): m
        for m in Medicament.objects.filter(id_etablissement_id=id_hopital, id_medicament__in=ids)
    }
    if len(medicaments) != len(ids):
        raise ValidationError({"lignes": "Chaque médicament prescrit doit appartenir au catalogue de l'hôpital."})
    resultat = []
    for ligne in lignes:
        try:
            quantite = int(ligne["quantite_prescrite"])
            duree = int(ligne["duree_traitement"])
        except (TypeError, ValueError) as exc:
            raise ValidationError({"lignes": "Quantité et durée doivent être des entiers positifs."}) from exc
        resultat.append(
            LignePrescription.objects.create(
                id_prescription=prescription,
                id_medicament=medicaments[str(ligne["id_medicament"])],
                posologie=ligne["posologie"],
                quantite_prescrite=quantite,
                duree_traitement=duree,
                id_etablissement_id=id_hopital,
            )
        )
    JournalAction.objects.create(
        type_action="prescription",
        details=f"Prescription {prescription.id_prescription} rédigée",
        matricule_personnel_id=matricule_medecin,
        id_etablissement_id=id_hopital,
    )
    return prescription, resultat


def alertes_reapprovisionnement():
    """Médicaments dont le stock vendable cumulé est sous leur seuil (RG20)."""
    aujourd_hui = timezone.localdate()
    return (
        Medicament.objects.annotate(
            stock_disponible=Coalesce(
                Sum("lots__quantite_stock", filter=Q(lots__date_peremption__gte=aujourd_hui)),
                Value(0),
            )
        )
        .filter(stock_disponible__lt=F("seuil_alerte"))
        .order_by("nom_medicament", "code_medicament")
    )


def alertes_peremption(*, delai_jours=90):
    """Lots en stock dont la date d'expiration est atteinte ou proche (RG39)."""
    if delai_jours < 0:
        raise ValueError("delai_jours doit être positif ou nul.")
    aujourd_hui = timezone.localdate()
    limite = aujourd_hui + timedelta(days=delai_jours)
    return LotMedicament.objects.filter(
        date_peremption__lte=limite,
        quantite_stock__gt=0,
    ).select_related("id_medicament").order_by("date_peremption", "numero_lot")