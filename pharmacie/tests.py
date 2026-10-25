"""
Tests du Bloc 4 : isolation RLS, catalogue et lots, délivrance (RG17, RG18, RG40),
pharmacie rattachée à un hôpital (RG19-a), pharmacie indépendante (RG19-b, RG31, RG38),
paiement (décision D5), exception hôpital -> pharmacie, alertes (RG20, RG39).

Même principe que les Blocs 2 et 3 : les données sont créées avec la variable de session
positionnée sur l'établissement concerné (self.positionner), puis les opérations et les
assertions s'exécutent dans `self.session(...)`, où la RLS est réellement appliquée.

Ces tests appellent les modèles et les services, jamais l'API.
"""

import datetime
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from core.db.rls import current_tenant
from core.testing import RLSTestCase
from etablissements.models import Etablissement, Hopital, Medecin, Personnel, Pharmacie
from patients.models import Client, Patient
from pharmacie.models import LignePrescription, LigneVente, LotMedicament, Medicament, Prescription, Vente
from pharmacie.services import (
    PharmacieError,
    alertes_peremption,
    alertes_reapprovisionnement,
    consulter_prescription_hospitaliere,
    enregistrer_vente,
)
from soins.models import Acte, Consultation

CLIENT_PAR_DEFAUT = {"nom": "Ndayizeye", "prenom": "Jean", "telephone_contact": "+25779000001"}


def dans(jours):
    """Date relative à aujourd'hui (négatif = déjà passée)."""
    return timezone.localdate() + timedelta(days=jours)


def ligne(medicament, quantite):
    return {"id_medicament": medicament.pk, "quantite": quantite}


# --------------------------------------------------------------------------- fabriques


def creer_etablissement(nom, type_etablissement):
    return Etablissement.objects.create(
        nom_etablissement=nom, type_etablissement=type_etablissement, adresse="Bujumbura", telephone_contact="+25722000000"
    )


def creer_hopital(nom):
    etablissement = creer_etablissement(nom, Etablissement.TYPE_HOPITAL)
    Hopital.objects.create(id_etablissement=etablissement, numero_agrement=f"AGR-{nom}"[:30])
    return etablissement


def creer_pharmacie(nom, hopital=None):
    etablissement = creer_etablissement(nom, Etablissement.TYPE_PHARMACIE)
    Pharmacie.objects.create(
        id_etablissement=etablissement,
        numero_agrement_pharmaceutique=f"PH-{nom}"[:30],
        id_etablissement_hopital_rattachement=Hopital.objects.get(pk=hopital.pk) if hopital else None,
    )
    return etablissement


def creer_personnel(etablissement, identifiant, role_metier):
    return Personnel.objects.create_user(
        identifiant_connexion=identifiant,
        email_professionnel=f"{identifiant}@example.org",
        password="x",
        nom="Nom",
        prenom="Prenom",
        role_metier=role_metier,
        date_embauche=datetime.date(2026, 1, 1),
        role_acces="standard",
        id_etablissement=etablissement,
    )


def creer_medecin(etablissement, identifiant):
    personnel = creer_personnel(etablissement, identifiant, "medecin")
    return Medecin.objects.create(matricule_personnel=personnel, specialite="Générale")


def creer_patient(etablissement, nom, allergies=None):
    RLSTestCase.positionner(etablissement.pk)
    return Patient.objects.create(
        nom_patient=nom,
        prenom_patient="Jean",
        date_naissance=datetime.date(1990, 5, 17),
        sexe="M",
        allergies=allergies,
        id_etablissement=etablissement,
    )


def creer_consultation(etablissement, patient, medecin):
    RLSTestCase.positionner(etablissement.pk)
    acte = Acte.objects.create(
        date_acte=timezone.localdate(),
        libelle_acte="Consultation",
        montant_base=Decimal("10.00"),
        id_patient=patient,
        id_etablissement=etablissement,
    )
    return Consultation.objects.create(
        id_acte=acte, diagnostic="Paludisme", matricule_personnel=medecin, id_etablissement=etablissement
    )


def creer_medicament(etablissement, code, nom, prix="50", seuil=5, vente_libre=False):
    RLSTestCase.positionner(etablissement.pk)
    return Medicament.objects.create(
        code_medicament=code,
        nom_medicament=nom,
        dosage="500mg",
        forme="comprimé",
        prix_catalogue=Decimal(prix),
        seuil_alerte=seuil,
        vente_libre=vente_libre,
        id_etablissement=etablissement,
    )


def creer_lot(medicament, numero_lot, quantite, date_peremption):
    RLSTestCase.positionner(medicament.id_etablissement_id)
    return LotMedicament.objects.create(
        numero_lot=numero_lot,
        date_peremption=date_peremption,
        quantite_stock=quantite,
        id_medicament=medicament,
        id_etablissement_id=medicament.id_etablissement_id,
    )


def creer_prescription(hopital, medecin, patient, consultation, lignes):
    """`lignes` = liste de (medicament_de_l_hopital, quantite_prescrite)."""
    RLSTestCase.positionner(hopital.pk)
    prescription = Prescription.objects.create(
        date_prescription=timezone.localdate(),
        matricule_personnel=medecin,
        id_patient=patient,
        id_acte_consultation=consultation,
        id_etablissement=hopital,
    )
    for medicament, quantite in lignes:
        LignePrescription.objects.create(
            id_prescription=prescription,
            id_medicament=medicament,
            posologie="1 cp x 3/j",
            quantite_prescrite=quantite,
            duree_traitement=5,
            id_etablissement=hopital,
        )
    return prescription


# --------------------------------------------------------------------------- base commune


class BasePharmacie(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Établissements : 2 hôpitaux, 3 pharmacies rattachées, 2 pharmacies indépendantes.
        cls.hopital = creer_hopital("Hopital A")
        cls.autre_hopital = creer_hopital("Hopital B")
        cls.pharmacie_rattachee = creer_pharmacie("Pharma A1", cls.hopital)
        cls.pharmacie_rattachee_2 = creer_pharmacie("Pharma A2", cls.hopital)
        cls.pharmacie_autre_hopital = creer_pharmacie("Pharma B1", cls.autre_hopital)
        cls.pharmacie_independante = creer_pharmacie("Pharma I1")
        cls.pharmacie_independante_2 = creer_pharmacie("Pharma I2")

        # Personnel.
        cls.medecin = creer_medecin(cls.hopital, "dr_a")
        cls.ph_rattache = creer_personnel(cls.pharmacie_rattachee, "pharm_a1", "pharmacien")
        cls.ph_rattache_2 = creer_personnel(cls.pharmacie_rattachee_2, "pharm_a2", "pharmacien")
        cls.ph_autre_hopital = creer_personnel(cls.pharmacie_autre_hopital, "pharm_b1", "pharmacien")
        cls.ph_indep = creer_personnel(cls.pharmacie_independante, "pharm_i1", "pharmacien")
        cls.ph_indep_2 = creer_personnel(cls.pharmacie_independante_2, "pharm_i2", "pharmacien")

        # Hôpital A : un patient, une consultation, une prescription de 2 médicaments.
        cls.patient = creer_patient(cls.hopital, "Nzeyimana", allergies="Pénicilline")
        consultation = creer_consultation(cls.hopital, cls.patient, cls.medecin)
        cls.med_h_para = creer_medicament(cls.hopital, "PARA500", "Paracétamol", "100")
        cls.med_h_amox = creer_medicament(cls.hopital, "AMOX250", "Amoxicilline", "300")
        cls.prescription = creer_prescription(
            cls.hopital, cls.medecin, cls.patient, consultation, [(cls.med_h_para, 5), (cls.med_h_amox, 10)]
        )

        # Catalogues des pharmacies (aucun catalogue partagé, RG34). AMOX250 manque volontairement
        # dans les pharmacies rattachées : le médicament prescrit n'y est pas disponible.
        cls.para_r1 = creer_medicament(cls.pharmacie_rattachee, "PARA500", "Paracétamol", "100")
        creer_lot(cls.para_r1, "R1-L1", 50, dans(365))
        cls.para_r2 = creer_medicament(cls.pharmacie_rattachee_2, "PARA500", "Paracétamol", "100")
        creer_lot(cls.para_r2, "R2-L1", 50, dans(365))
        cls.para_b = creer_medicament(cls.pharmacie_autre_hopital, "PARA500", "Paracétamol", "100")
        creer_lot(cls.para_b, "B-L1", 50, dans(365))

        cls.vl_i1 = creer_medicament(cls.pharmacie_independante, "VL001", "Vitamine C", "50", vente_libre=True)
        creer_lot(cls.vl_i1, "I1-VL", 100, dans(365))
        cls.ord_i1 = creer_medicament(cls.pharmacie_independante, "ORD001", "Antibiotique", "500", vente_libre=False)
        cls.lot_ord_i1 = creer_lot(cls.ord_i1, "I1-ORD", 100, dans(365))
        cls.vl_i2 = creer_medicament(cls.pharmacie_independante_2, "VL001", "Vitamine C", "50", vente_libre=True)
        creer_lot(cls.vl_i2, "I2-VL", 100, dans(365))

    def setUp(self):
        self.positionner(self.pharmacie_independante.pk)

    # ------------------------------------------------------------------ aides aux tests

    def nouveau_medicament(self, pharmacie, code, **extra):
        return creer_medicament(pharmacie, code, f"Médicament {code}", **extra)

    def vente_independante(self, lignes, *, pharmacie=None, pharmacien=None, client=None, moyen="especes", **extra):
        pharmacie = pharmacie or self.pharmacie_independante
        pharmacien = pharmacien or self.ph_indep
        with self.session(pharmacie):
            return enregistrer_vente(
                id_pharmacie=pharmacie.pk,
                matricule_personnel=pharmacien.pk,
                lignes=lignes,
                client=client or CLIENT_PAR_DEFAUT,
                moyen_paiement=moyen,
                **extra,
            )

    def vente_rattachee(self, lignes, *, pharmacie=None, pharmacien=None, id_patient=None, id_prescription=None, **extra):
        pharmacie = pharmacie or self.pharmacie_rattachee
        pharmacien = pharmacien or self.ph_rattache
        with self.session(pharmacie):
            return enregistrer_vente(
                id_pharmacie=pharmacie.pk,
                matricule_personnel=pharmacien.pk,
                lignes=lignes,
                id_patient=self.patient.pk if id_patient is None else id_patient,
                id_prescription=self.prescription.pk if id_prescription is None else id_prescription,
                **extra,
            )


# --------------------------------------------------------------------------- isolation RLS


class IsolationRLSBloc4Tests(BasePharmacie):
    def test_le_role_de_test_ne_contourne_pas_la_rls(self):
        with self.session(self.pharmacie_independante), connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            self.assertFalse(cursor.fetchone()[0])

    def test_chaque_pharmacie_ne_voit_que_son_catalogue_et_ses_lots(self):
        for pharmacie in (self.pharmacie_independante, self.pharmacie_independante_2):
            with self.session(pharmacie):
                for modele in (Medicament, LotMedicament):
                    lignes = list(modele.objects.all())
                    self.assertTrue(lignes, f"{modele.__name__} : rien de visible pour {pharmacie}")
                    self.assertEqual({l.id_etablissement_id for l in lignes}, {pharmacie.pk})

    def test_chaque_pharmacie_ne_voit_que_ses_ventes(self):
        vente_1, _ = self.vente_independante([ligne(self.vl_i1, 2)])
        vente_2, _ = self.vente_independante(
            [ligne(self.vl_i2, 3)], pharmacie=self.pharmacie_independante_2, pharmacien=self.ph_indep_2
        )
        with self.session(self.pharmacie_independante):
            self.assertEqual({v.pk for v in Vente.objects.all()}, {vente_1.pk})
            self.assertEqual({l.id_vente_id for l in LigneVente.objects.all()}, {vente_1.pk})
            self.assertFalse(Vente.objects.filter(pk=vente_2.pk).exists())
        with self.session(self.pharmacie_independante_2):
            self.assertEqual({v.pk for v in Vente.objects.all()}, {vente_2.pk})
            self.assertFalse(Vente.objects.filter(pk=vente_1.pk).exists())

    def test_une_pharmacie_rattachee_ne_lit_aucune_donnee_d_hopital_directement(self):
        with self.session(self.pharmacie_rattachee):
            self.assertEqual(Prescription.objects.count(), 0)
            self.assertEqual(LignePrescription.objects.count(), 0)
            self.assertEqual(Patient.objects.count(), 0)

    def test_l_hopital_ne_voit_pas_le_catalogue_de_sa_pharmacie(self):
        with self.session(self.hopital):
            self.assertEqual(LotMedicament.objects.count(), 0)
            self.assertEqual({m.id_etablissement_id for m in Medicament.objects.all()}, {self.hopital.pk})


# --------------------------------------------------------------------------- catalogue et stock


class CatalogueEtStockTests(BasePharmacie):
    def test_code_medicament_unique_par_etablissement_mais_reutilisable_ailleurs(self):
        # PARA500 existe déjà dans plusieurs établissements : la création a réussi (RG34).
        self.nouveau_medicament(self.pharmacie_independante, "DUP001")
        with self.assertRaises(ValidationError):
            self.nouveau_medicament(self.pharmacie_independante, "DUP001")
        # Le même code dans une autre pharmacie est accepté.
        self.nouveau_medicament(self.pharmacie_independante_2, "DUP001")

    def test_le_stock_est_la_somme_des_lots_non_perimes(self):
        medicament = self.nouveau_medicament(self.pharmacie_independante, "STK001", vente_libre=True)
        creer_lot(medicament, "L1", 10, dans(30))
        creer_lot(medicament, "L2", 5, dans(60))
        creer_lot(medicament, "LP", 7, dans(-1))  # périmé : exclu
        with self.session(self.pharmacie_independante):
            self.assertEqual(Medicament.objects.get(pk=medicament.pk).quantite_stock, 15)

    def test_un_lot_perime_n_est_jamais_vendu(self):
        medicament = self.nouveau_medicament(self.pharmacie_independante, "STK002", vente_libre=True)
        lot_perime = creer_lot(medicament, "LP", 7, dans(-1))
        creer_lot(medicament, "L1", 3, dans(30))
        _, livrees = self.vente_independante([ligne(medicament, 5)])
        self.assertEqual(livrees["STK002"], 3)  # seul le lot valide est utilisé
        with self.session(self.pharmacie_independante):
            self.assertEqual(LotMedicament.objects.get(pk=lot_perime.pk).quantite_stock, 7)

    def test_stock_nul_ou_seulement_perime_la_vente_est_refusee(self):
        vide = self.nouveau_medicament(self.pharmacie_independante, "STK003", vente_libre=True)
        creer_lot(vide, "L0", 0, dans(30))
        perime = self.nouveau_medicament(self.pharmacie_independante, "STK004", vente_libre=True)
        creer_lot(perime, "LP", 9, dans(-1))
        for medicament in (vide, perime):
            with self.assertRaises(ValidationError):
                self.vente_independante([ligne(medicament, 1)])
        with self.session(self.pharmacie_independante):
            self.assertEqual(Vente.objects.count(), 0)  # rien n'a été enregistré


# --------------------------------------------------------------------------- délivrance


class DelivranceTests(BasePharmacie):
    def test_rg40_vente_repartie_sur_plusieurs_lots_le_plus_proche_d_abord(self):
        medicament = self.nouveau_medicament(self.pharmacie_independante, "LOT001", vente_libre=True)
        lot_proche = creer_lot(medicament, "A-PROCHE", 3, dans(10))
        lot_moyen = creer_lot(medicament, "B-MOYEN", 4, dans(30))
        lot_loin = creer_lot(medicament, "C-LOIN", 10, dans(90))
        vente, livrees = self.vente_independante([ligne(medicament, 8)])
        self.assertEqual(livrees["LOT001"], 8)
        with self.session(self.pharmacie_independante):
            lignes = list(LigneVente.objects.filter(id_vente=vente))
            self.assertEqual(len(lignes), 3)  # une ligne par lot (RG40)
            self.assertEqual(
                {l.id_lot_id: l.quantite_delivree for l in lignes},
                {lot_proche.pk: 3, lot_moyen.pk: 4, lot_loin.pk: 1},
            )
            self.assertEqual(sum(l.quantite_demandee for l in lignes), 8)
            self.assertEqual(LotMedicament.objects.get(pk=lot_proche.pk).quantite_stock, 0)
            self.assertEqual(LotMedicament.objects.get(pk=lot_moyen.pk).quantite_stock, 0)
            self.assertEqual(LotMedicament.objects.get(pk=lot_loin.pk).quantite_stock, 9)

    def test_rg18_delivrance_partielle_quand_le_stock_est_insuffisant(self):
        medicament = self.nouveau_medicament(self.pharmacie_independante, "PART001", vente_libre=True)
        lot = creer_lot(medicament, "P1", 5, dans(30))
        vente, livrees = self.vente_independante([ligne(medicament, 8)])
        self.assertEqual(livrees["PART001"], 5)
        with self.session(self.pharmacie_independante):
            ligne_vente = LigneVente.objects.get(id_vente=vente)
            self.assertEqual(ligne_vente.quantite_demandee, 8)
            self.assertEqual(ligne_vente.quantite_delivree, 5)
            self.assertEqual(LotMedicament.objects.get(pk=lot.pk).quantite_stock, 0)  # jamais négatif

    def test_rg17_le_prix_facture_ne_change_pas_si_le_catalogue_change(self):
        medicament = self.nouveau_medicament(self.pharmacie_independante, "PRIX001", prix="50", vente_libre=True)
        creer_lot(medicament, "X1", 10, dans(30))
        vente, _ = self.vente_independante([ligne(medicament, 2)])
        with self.session(self.pharmacie_independante):
            medicament = Medicament.objects.get(pk=medicament.pk)
            medicament.prix_catalogue = Decimal("80")
            medicament.save()
            self.assertEqual(LigneVente.objects.get(id_vente=vente).prix_facture, Decimal("50.00"))

    def test_la_vente_decremente_le_stock_du_lot(self):
        with self.session(self.pharmacie_independante):
            avant = Medicament.objects.get(pk=self.vl_i1.pk).quantite_stock
        self.vente_independante([ligne(self.vl_i1, 4)])
        with self.session(self.pharmacie_independante):
            self.assertEqual(Medicament.objects.get(pk=self.vl_i1.pk).quantite_stock, avant - 4)

    def test_un_medicament_ne_peut_apparaitre_qu_une_fois_et_la_quantite_doit_etre_positive(self):
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.vl_i1, 1), ligne(self.vl_i1, 2)])
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.vl_i1, 0)])
        with self.assertRaises(ValidationError):
            self.vente_independante([])


# --------------------------------------------------------------------------- pharmacie rattachée


class PharmacieRattacheeTests(BasePharmacie):
    def test_rg19a_refus_sans_patient_ou_sans_prescription(self):
        with self.session(self.pharmacie_rattachee):
            for kwargs in ({}, {"id_patient": self.patient.pk}, {"id_prescription": self.prescription.pk}):
                with self.assertRaises(ValidationError):
                    enregistrer_vente(
                        id_pharmacie=self.pharmacie_rattachee.pk,
                        matricule_personnel=self.ph_rattache.pk,
                        lignes=[ligne(self.para_r1, 1)],
                        **kwargs,
                    )

    def test_vente_rattachee_avec_prescription_valide(self):
        vente, livrees = self.vente_rattachee([ligne(self.para_r1, 2)])
        self.assertEqual(livrees, {"PARA500": 2})
        with self.session(self.pharmacie_rattachee):
            vente = Vente.objects.get(pk=vente.pk)
            self.assertEqual(vente.id_patient_id, self.patient.pk)
            self.assertEqual(vente.id_prescription_id, self.prescription.pk)
            self.assertIsNone(vente.id_client_id)
            self.assertIsNone(vente.statut_paiement)  # le paiement passe par la facture de l'hôpital

    def test_le_statut_de_paiement_est_refuse_en_pharmacie_rattachee(self):
        with self.assertRaises(ValidationError):
            self.vente_rattachee([ligne(self.para_r1, 1)], statut_paiement="paye")

    def test_patient_different_de_celui_de_la_prescription(self):
        with self.assertRaises(ValidationError):
            self.vente_rattachee([ligne(self.para_r1, 1)], id_patient=uuid.uuid4())

    def test_medicament_absent_de_la_prescription(self):
        autre = self.nouveau_medicament(self.pharmacie_rattachee, "IBU400")
        creer_lot(autre, "R1-IBU", 20, dans(200))
        with self.assertRaises(ValidationError):
            self.vente_rattachee([ligne(autre, 1)])

    def test_on_ne_delivre_pas_plus_que_la_quantite_prescrite(self):
        with self.assertRaises(ValidationError):
            self.vente_rattachee([ligne(self.para_r1, 6)])  # 5 prescrits

    def test_prescription_cumulee_sur_toutes_les_pharmacies_de_l_hopital(self):
        self.vente_rattachee([ligne(self.para_r1, 3)])  # reste 2
        with self.assertRaises(ValidationError):
            self.vente_rattachee(
                [ligne(self.para_r2, 3)], pharmacie=self.pharmacie_rattachee_2, pharmacien=self.ph_rattache_2
            )
        self.vente_rattachee(
            [ligne(self.para_r2, 2)], pharmacie=self.pharmacie_rattachee_2, pharmacien=self.ph_rattache_2
        )
        with self.assertRaises(ValidationError):  # plus rien à délivrer
            self.vente_rattachee([ligne(self.para_r1, 1)])

    def test_la_vente_doit_etre_faite_par_un_pharmacien_de_la_pharmacie(self):
        with self.assertRaises(ValidationError):
            self.vente_rattachee([ligne(self.para_r1, 1)], pharmacien=self.ph_indep)


class ExceptionHopitalPharmacieTests(BasePharmacie):
    """La seule lecture inter-établissements : une pharmacie rattachée consulte l'ordonnance de SON hôpital."""

    def consulter(self, pharmacie, id_prescription=None):
        with self.session(pharmacie):
            return consulter_prescription_hospitaliere(
                id_pharmacie=pharmacie.pk, id_prescription=id_prescription or self.prescription.pk
            )

    def test_la_consultation_n_expose_ni_le_nom_ni_les_allergies_du_patient(self):
        resultat = self.consulter(self.pharmacie_rattachee)
        self.assertEqual(
            set(resultat.keys()), {"id_prescription", "id_patient", "date_prescription", "lignes"}
        )
        self.assertEqual(resultat["id_patient"], self.patient.pk)
        for contenu in resultat["lignes"]:
            self.assertEqual(
                set(contenu.keys()),
                {
                    "code_medicament",
                    "disponible_dans_cette_pharmacie",
                    "nom_medicament",
                    "dosage",
                    "posologie",
                    "quantite_prescrite",
                    "duree_traitement",
                },
            )
        texte = repr(resultat)
        self.assertNotIn("Nzeyimana", texte)
        self.assertNotIn("Pénicilline", texte)

    def test_d1_indique_quels_medicaments_prescrits_existent_au_catalogue_de_la_pharmacie(self):
        resultat = self.consulter(self.pharmacie_rattachee)
        disponibilite = {l["code_medicament"]: l["disponible_dans_cette_pharmacie"] for l in resultat["lignes"]}
        self.assertEqual(disponibilite, {"PARA500": True, "AMOX250": False})

    def test_une_pharmacie_independante_ne_lit_aucune_ordonnance_d_hopital(self):
        with self.assertRaises(ValidationError):
            self.consulter(self.pharmacie_independante)
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.vl_i1, 1)], id_prescription=self.prescription.pk)

    def test_une_pharmacie_ne_lit_pas_l_ordonnance_d_un_autre_hopital(self):
        with self.assertRaises(ValidationError):
            self.consulter(self.pharmacie_autre_hopital)

    def test_la_session_doit_etre_positionnee_sur_la_pharmacie(self):
        with self.session(self.pharmacie_independante):
            with self.assertRaises(PharmacieError):
                consulter_prescription_hospitaliere(
                    id_pharmacie=self.pharmacie_rattachee.pk, id_prescription=self.prescription.pk
                )

    def test_le_contexte_rls_est_restaure_apres_la_bascule_temporaire(self):
        with self.session(self.pharmacie_rattachee):
            attendu = str(self.pharmacie_rattachee.pk)
            consulter_prescription_hospitaliere(
                id_pharmacie=self.pharmacie_rattachee.pk, id_prescription=self.prescription.pk
            )
            self.assertEqual(current_tenant(), attendu)
            with self.assertRaises(ValidationError):  # erreur levée DANS la bascule
                consulter_prescription_hospitaliere(
                    id_pharmacie=self.pharmacie_rattachee.pk, id_prescription=uuid.uuid4()
                )
            self.assertEqual(current_tenant(), attendu)


# --------------------------------------------------------------------------- pharmacie indépendante


class PharmacieIndependanteTests(BasePharmacie):
    def test_vente_libre_sans_ordonnance_acceptee(self):
        vente, livrees = self.vente_independante([ligne(self.vl_i1, 2)])
        self.assertEqual(livrees, {"VL001": 2})
        with self.session(self.pharmacie_independante):
            vente = Vente.objects.get(pk=vente.pk)
            self.assertIsNone(vente.id_patient_id)
            self.assertIsNotNone(vente.id_client_id)

    def test_hors_vente_libre_refuse_sans_prescripteur_externe(self):
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.ord_i1, 1)])

    def test_d2_hors_vente_libre_refuse_si_la_date_du_prescripteur_manque(self):
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.ord_i1, 1)], nom_prescripteur_externe="Dr Niyonzima")

    def test_hors_vente_libre_accepte_avec_nom_et_date_du_prescripteur(self):
        vente, livrees = self.vente_independante(
            [ligne(self.ord_i1, 1)],
            nom_prescripteur_externe="Dr Niyonzima",
            date_prescription_externe=timezone.localdate(),
        )
        self.assertEqual(livrees, {"ORD001": 1})

    def test_rg31_la_fiche_client_est_creee_puis_mise_a_jour(self):
        self.vente_independante(
            [ligne(self.vl_i1, 1)],
            client={"nom": "Ndayizeye", "prenom": "Jean", "telephone_contact": "+25779123456"},
        )
        with self.session(self.pharmacie_independante):
            self.assertEqual(Client.objects.count(), 1)
        vente, _ = self.vente_independante(
            [ligne(self.vl_i1, 1)],
            client={"nom": "Ndayizeye", "prenom": "Jean-Paul", "telephone_contact": "+25779123456"},
        )
        with self.session(self.pharmacie_independante):
            self.assertEqual(Client.objects.count(), 1)  # mise à jour, pas de doublon
            client = Client.objects.get()
            self.assertEqual(client.prenom, "Jean-Paul")
            self.assertEqual(Vente.objects.get(pk=vente.pk).id_client_id, client.pk)

    def test_une_vente_independante_exige_les_informations_du_client(self):
        with self.session(self.pharmacie_independante):
            with self.assertRaises(ValidationError):
                enregistrer_vente(
                    id_pharmacie=self.pharmacie_independante.pk,
                    matricule_personnel=self.ph_indep.pk,
                    lignes=[ligne(self.vl_i1, 1)],
                    moyen_paiement="especes",
                )

    def test_d5_statut_paye_automatique(self):
        vente, _ = self.vente_independante([ligne(self.vl_i1, 1)])
        with self.session(self.pharmacie_independante):
            vente = Vente.objects.get(pk=vente.pk)
            self.assertEqual(vente.statut_paiement, Vente.PAYE)
            self.assertEqual(vente.moyen_paiement, "especes")

    def test_d5_le_moyen_de_paiement_est_obligatoire_et_controle(self):
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.vl_i1, 1)], moyen=None)
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.vl_i1, 1)], moyen="")
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.vl_i1, 1)], moyen="bitcoin")
        with self.session(self.pharmacie_independante):
            self.assertEqual(Vente.objects.count(), 0)

    def test_une_vente_ne_peut_pas_etre_creee_directement_annulee(self):
        with self.assertRaises(ValidationError):
            self.vente_independante([ligne(self.vl_i1, 1)], statut_paiement=Vente.ANNULE)

    def test_les_trois_moyens_de_paiement_sont_acceptes(self):
        for moyen in (Vente.ESPECES, Vente.MOBILE_MONEY, Vente.CARTE):
            vente, _ = self.vente_independante([ligne(self.vl_i1, 1)], moyen=moyen)
            with self.session(self.pharmacie_independante):
                self.assertEqual(Vente.objects.get(pk=vente.pk).moyen_paiement, moyen)


# --------------------------------------------------------------------------- contraintes et validation


class ContraintesEtValidationTests(BasePharmacie):
    def nouvelle_vente(self, **champs):
        base = dict(
            id_etablissement=self.pharmacie_independante,
            matricule_personnel=self.ph_indep,
            statut_paiement=Vente.PAYE,
            moyen_paiement=Vente.ESPECES,
        )
        base.update(champs)
        return Vente(**base)

    def test_vente_save_direct_exige_un_patient_ou_un_client(self):
        self.positionner(self.pharmacie_independante.pk)
        with self.assertRaises(ValidationError):
            self.nouvelle_vente().save()  # ni patient ni client

    def test_vente_save_direct_exige_statut_et_moyen_en_pharmacie_independante(self):
        self.positionner(self.pharmacie_independante.pk)
        client = Client.objects.create(nom="Client", id_etablissement=self.pharmacie_independante)
        with self.assertRaises(ValidationError):
            self.nouvelle_vente(id_client=client, moyen_paiement=None).save()
        with self.assertRaises(ValidationError):
            self.nouvelle_vente(id_client=client, statut_paiement=None).save()
        self.nouvelle_vente(id_client=client).save()  # complète : acceptée

    def test_vente_save_direct_rattachee_ne_valide_pas_l_existence_cote_hopital(self):
        # Sous la RLS de la pharmacie, patient et prescription (hôpital) sont invisibles :
        # l'enregistrement direct doit pourtant réussir (leur existence est garantie par la FK).
        with self.session(self.pharmacie_rattachee):
            Vente(
                id_etablissement=self.pharmacie_rattachee,
                matricule_personnel=self.ph_rattache,
                id_patient_id=self.patient.pk,
                id_prescription_id=self.prescription.pk,
            ).save()

    def test_rg38_filet_de_securite_au_niveau_de_la_ligne(self):
        vente, _ = self.vente_independante([ligne(self.vl_i1, 1)])  # vente libre, sans prescripteur
        with self.session(self.pharmacie_independante):
            with self.assertRaises(ValidationError):
                LigneVente(
                    id_vente=vente,
                    id_medicament=self.ord_i1,
                    id_lot=self.lot_ord_i1,
                    quantite_demandee=1,
                    quantite_delivree=1,
                    prix_facture=Decimal("500"),
                    id_etablissement=self.pharmacie_independante,
                ).save()

    def test_contrainte_base_patient_ou_client_exclusif(self):
        self.positionner(self.pharmacie_independante.pk)
        client = Client.objects.create(nom="Client", id_etablissement=self.pharmacie_independante)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vente.objects.bulk_create(  # bulk_create contourne save() : seule la base protège
                    [self.nouvelle_vente(id_client=client, id_patient_id=self.patient.pk)]
                )

    def test_contrainte_base_prescription_interne_ou_externe_exclusif(self):
        self.positionner(self.pharmacie_rattachee.pk)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vente.objects.bulk_create(
                    [
                        Vente(
                            id_etablissement=self.pharmacie_rattachee,
                            matricule_personnel=self.ph_rattache,
                            id_patient_id=self.patient.pk,
                            id_prescription_id=self.prescription.pk,
                            nom_prescripteur_externe="Dr Externe",
                        )
                    ]
                )

    def test_contrainte_base_quantite_delivree_superieure_a_la_demande(self):
        vente, _ = self.vente_independante([ligne(self.vl_i1, 1)])
        autre_lot = creer_lot(self.vl_i1, "I1-VL-BIS", 10, dans(100))
        self.positionner(self.pharmacie_independante.pk)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LigneVente.objects.bulk_create(
                    [
                        LigneVente(
                            id_vente=vente,
                            id_medicament=self.vl_i1,
                            id_lot=autre_lot,
                            quantite_demandee=1,
                            quantite_delivree=2,
                            prix_facture=Decimal("50"),
                            id_etablissement=self.pharmacie_independante,
                        )
                    ]
                )


# --------------------------------------------------------------------------- alertes


class AlertesTests(BasePharmacie):
    def test_rg20_alerte_de_reapprovisionnement(self):
        sous_seuil = self.nouveau_medicament(self.pharmacie_independante, "ALR001", seuil=10)
        creer_lot(sous_seuil, "A1", 5, dans(200))
        suffisant = self.nouveau_medicament(self.pharmacie_independante, "ALR002", seuil=10)
        creer_lot(suffisant, "B1", 20, dans(200))
        seulement_perime = self.nouveau_medicament(self.pharmacie_independante, "ALR003", seuil=10)
        creer_lot(seulement_perime, "C1", 50, dans(-3))
        with self.session(self.pharmacie_independante):
            codes = {m.code_medicament for m in alertes_reapprovisionnement()}
        self.assertIn("ALR001", codes)
        self.assertNotIn("ALR002", codes)
        self.assertIn("ALR003", codes)  # le stock périmé ne compte pas

    def test_rg20_le_stock_de_plusieurs_lots_est_cumule(self):
        medicament = self.nouveau_medicament(self.pharmacie_independante, "ALR004", seuil=10)
        creer_lot(medicament, "D1", 6, dans(200))
        creer_lot(medicament, "D2", 6, dans(300))  # 12 au total, au-dessus du seuil
        with self.session(self.pharmacie_independante):
            codes = {m.code_medicament for m in alertes_reapprovisionnement()}
        self.assertNotIn("ALR004", codes)

    def test_rg39_alerte_de_peremption(self):
        medicament = self.nouveau_medicament(self.pharmacie_independante, "PER001")
        creer_lot(medicament, "PER-PROCHE", 4, dans(30))
        creer_lot(medicament, "PER-LOIN", 4, dans(200))
        creer_lot(medicament, "PER-VIDE", 0, dans(10))
        creer_lot(medicament, "PER-PASSE", 4, dans(-5))
        with self.session(self.pharmacie_independante):
            lots = {lot.numero_lot for lot in alertes_peremption()}
            lots_10_jours = {lot.numero_lot for lot in alertes_peremption(delai_jours=10)}
        self.assertIn("PER-PROCHE", lots)
        self.assertIn("PER-PASSE", lots)
        self.assertNotIn("PER-LOIN", lots)
        self.assertNotIn("PER-VIDE", lots)  # un lot épuisé n'alerte pas
        self.assertNotIn("PER-PROCHE", lots_10_jours)  # le délai est ajustable
        self.assertIn("PER-PASSE", lots_10_jours)

    def test_rg39_un_delai_negatif_est_refuse(self):
        with self.assertRaises(ValueError):
            alertes_peremption(delai_jours=-1)