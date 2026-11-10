"""
Tests du Bloc 3 : isolation RLS, rendez-vous (RG05), consultations (RG09-RG10),
hospitalisations, chambres et lits (RG11-RG14), contraintes et validations.

Même principe qu'au Bloc 2 : les données sont créées avec la variable de session
positionnée sur l'établissement concerné (self.positionner), puis les assertions
d'isolation s'exécutent dans `self.session(...)`, où la RLS est réellement appliquée.
"""

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import RLSTestCase
from etablissements.models import Etablissement, Medecin, Personnel, Service
from patients.models import Patient
from soins.models import Acte, Chambre, Consultation, Hospitalisation, Lit, RendezVous

JOUR = datetime.date(2026, 10, 21)
HEURE = datetime.time(9, 0)
MODELES = (RendezVous, Acte, Consultation, Chambre, Lit, Hospitalisation)


def creer_etablissement(nom, type_etablissement=Etablissement.TYPE_HOPITAL):
    return Etablissement.objects.create(
        nom_etablissement=nom, type_etablissement=type_etablissement, adresse="Bujumbura", telephone_contact="+25722000000"
    )


def creer_medecin(etablissement, identifiant, superviseur=None):
    personnel = Personnel.objects.create_user(
        identifiant_connexion=identifiant,
        email_professionnel=f"{identifiant}@example.org",
        password="x",
        nom="Nom",
        prenom="Prenom",
        role_metier="medecin",
        date_embauche=datetime.date(2026, 1, 1),
        role_acces="standard",
        id_etablissement=etablissement,
    )
    return Medecin.objects.create(matricule_personnel=personnel, specialite="Générale", matricule_superviseur=superviseur)


def creer_patient(etablissement, nom):
    RLSTestCase.positionner(etablissement.pk)
    return Patient.objects.create(
        nom_patient=nom,
        prenom_patient="Jean",
        date_naissance=datetime.date(1990, 5, 17),
        sexe="M",
        id_etablissement=etablissement,
    )


def creer_acte(etablissement, patient, libelle="Acte", montant="10.00"):
    return Acte.objects.create(
        date_acte=JOUR, libelle_acte=libelle, montant_base=Decimal(montant), id_patient=patient, id_etablissement=etablissement
    )


def creer_consultation(etablissement, patient, medecin, **extra):
    acte = creer_acte(etablissement, patient, "Consultation")
    return Consultation.objects.create(
        id_acte=acte, diagnostic="Paludisme", matricule_personnel=medecin, id_etablissement=etablissement, **extra
    )


def creer_hospitalisation(etablissement, patient, consultation, **extra):
    acte = creer_acte(etablissement, patient, "Hospitalisation")
    return Hospitalisation.objects.create(
        id_acte=acte, date_entree=JOUR, id_acte_consultation=consultation, id_etablissement=etablissement, **extra
    )


def construire_parcours(etablissement, medecin, patient, nom_service):
    """Une ligne dans chacune des 6 tables du bloc, toutes pour `etablissement`."""
    RLSTestCase.positionner(etablissement.pk)
    service = Service.objects.create(nom_service=nom_service, id_etablissement=etablissement)
    chambre = Chambre.objects.create(numero_chambre="101", code_service=service, id_etablissement=etablissement)
    lit = Lit.objects.create(numero_lit="1", id_chambre=chambre, id_etablissement=etablissement)
    rdv = RendezVous.objects.create(
        date_rendez_vous=JOUR, heure_rendez_vous=HEURE, id_patient=patient, matricule_personnel=medecin,
        id_etablissement=etablissement,
    )
    consultation = creer_consultation(etablissement, patient, medecin, id_rendez_vous=rdv)
    hospitalisation = creer_hospitalisation(etablissement, patient, consultation, id_chambre=chambre, id_lit=lit)
    return {
        "service": service, "chambre": chambre, "lit": lit, "rdv": rdv,
        "consultation": consultation, "hospitalisation": hospitalisation,
    }


class BaseBloc3(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hopital_a = creer_etablissement("Hôpital A")
        cls.hopital_b = creer_etablissement("Hôpital B")
        cls.medecin_a = creer_medecin(cls.hopital_a, "dr_a")
        cls.interne_a = creer_medecin(cls.hopital_a, "interne_a", superviseur=cls.medecin_a.matricule_personnel)
        cls.medecin_b = creer_medecin(cls.hopital_b, "dr_b")
        cls.patient_a = creer_patient(cls.hopital_a, "Alpha")
        cls.patient_a2 = creer_patient(cls.hopital_a, "Alpha2")
        cls.patient_b = creer_patient(cls.hopital_b, "Beta")
        cls.parcours_a = construire_parcours(cls.hopital_a, cls.medecin_a, cls.patient_a, "Chirurgie")
        cls.parcours_b = construire_parcours(cls.hopital_b, cls.medecin_b, cls.patient_b, "Chirurgie")

    def setUp(self):
        # Chaque test démarre « connecté » à l'hôpital A pour créer ses données.
        self.positionner(self.hopital_a.pk)


class IsolationRLSBloc3Tests(BaseBloc3):
    def test_le_role_de_test_ne_contourne_pas_la_rls(self):
        with self.session(self.hopital_a), connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            self.assertFalse(cursor.fetchone()[0])

    def test_chaque_hopital_ne_voit_que_ses_lignes_dans_les_6_tables(self):
        for etablissement in (self.hopital_a, self.hopital_b):
            with self.session(etablissement):
                for modele in MODELES:
                    lignes = list(modele.objects.all())
                    self.assertTrue(lignes, f"{modele.__name__} : aucune ligne visible pour {etablissement}")
                    self.assertEqual(
                        {ligne.id_etablissement_id for ligne in lignes},
                        {etablissement.pk},
                        f"{modele.__name__} : fuite entre établissements",
                    )

    def test_sans_contexte_aucune_ligne_visible(self):
        with self.session(None):
            for modele in MODELES:
                self.assertEqual(modele.objects.count(), 0, modele.__name__)

    def test_hopital_a_ne_peut_ni_modifier_ni_supprimer_les_lignes_de_b(self):
        cibles = {
            RendezVous: self.parcours_b["rdv"].pk,
            Acte: self.parcours_b["consultation"].pk,
            Consultation: self.parcours_b["consultation"].pk,
            Chambre: self.parcours_b["chambre"].pk,
            Lit: self.parcours_b["lit"].pk,
            Hospitalisation: self.parcours_b["hospitalisation"].pk,
        }
        with self.session(self.hopital_a):
            self.assertEqual(Chambre.objects.filter(pk=cibles[Chambre]).update(numero_chambre="X"), 0)
            self.assertEqual(Consultation.objects.filter(pk=cibles[Consultation]).update(diagnostic="X"), 0)
            self.assertEqual(
                Hospitalisation.objects.filter(pk=cibles[Hospitalisation]).update(date_sortie=JOUR), 0
            )
            for modele, pk in cibles.items():
                self.assertEqual(
                    modele.objects.filter(pk=pk)._raw_delete(using="default"), 0, f"{modele.__name__} supprimé à tort"
                )
        with self.session(self.hopital_b):
            for modele, pk in cibles.items():
                self.assertTrue(modele.objects.filter(pk=pk).exists(), modele.__name__)

    def test_hopital_a_ne_peut_pas_inserer_une_ligne_au_nom_de_b(self):
        with self.session(self.hopital_a), self.assertRaises(DatabaseError), transaction.atomic():
            Chambre.objects.bulk_create(
                [Chambre(numero_chambre="999", code_service=self.parcours_a["service"], id_etablissement=self.hopital_b)]
            )

    def test_hopital_a_ne_peut_pas_rattacher_un_lit_ou_une_chambre_de_b(self):
        consultation = creer_consultation(self.hopital_a, self.patient_a2, self.medecin_a)
        with self.session(self.hopital_a):
            with self.assertRaises(ValidationError):
                creer_hospitalisation(
                    self.hopital_a, self.patient_a2, consultation,
                    id_chambre=self.parcours_b["chambre"], id_lit=self.parcours_b["lit"],
                )
            with self.assertRaises(ValidationError):
                Lit.objects.create(numero_lit="7", id_chambre=self.parcours_b["chambre"], id_etablissement=self.hopital_a)
            with self.assertRaises(ValidationError):
                RendezVous.objects.create(
                    date_rendez_vous=JOUR, heure_rendez_vous=datetime.time(15, 0),
                    id_patient=self.patient_b, matricule_personnel=self.medecin_a, id_etablissement=self.hopital_a,
                )



class RendezVousTests(BaseBloc3):
    def nouveau_rdv(self, heure, **extra):
        valeurs = dict(
            date_rendez_vous=JOUR, heure_rendez_vous=heure, id_patient=self.patient_a2,
            matricule_personnel=self.medecin_a, id_etablissement=self.hopital_a,
        )
        valeurs.update(extra)
        return RendezVous.objects.create(**valeurs)

    def test_un_medecin_ne_peut_pas_avoir_deux_rendez_vous_sur_le_meme_creneau_rg05(self):
        # Le créneau 09:00 est déjà pris par le parcours de l'hôpital A.
        with self.assertRaises(ValidationError):
            self.nouveau_rdv(HEURE)

    def test_un_rendez_vous_annule_libere_le_creneau(self):
        rdv = self.parcours_a["rdv"]
        rdv.statut_rendez_vous = RendezVous.ANNULE
        rdv.save()
        self.nouveau_rdv(HEURE)

    def test_la_base_refuse_aussi_un_doublon_de_creneau(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RendezVous.objects.bulk_create(
                [
                    RendezVous(
                        date_rendez_vous=JOUR, heure_rendez_vous=HEURE, id_patient=self.patient_a2,
                        matricule_personnel=self.medecin_a, id_etablissement=self.hopital_a,
                    )
                ]
            )

    def test_statut_inconnu_refuse(self):
        with self.assertRaises(ValidationError):
            self.nouveau_rdv(datetime.time(10, 0), statut_rendez_vous="zzz")


    def test_medecin_d_un_autre_hopital_refuse(self):
        with self.assertRaises(ValidationError):
            self.nouveau_rdv(datetime.time(11, 0), matricule_personnel=self.medecin_b)

    def test_sans_etablissement_validation_error_et_clean_ne_plante_pas(self):
        rdv = RendezVous(
            date_rendez_vous=JOUR, heure_rendez_vous=HEURE, id_patient=self.patient_a, matricule_personnel=self.medecin_a
        )
        rdv.clean()
        with self.assertRaises(ValidationError) as cm:
            rdv.save()
        self.assertIn("id_etablissement", cm.exception.message_dict)

class RendezVousAPITests(BaseBloc3):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_login(self.medecin_a.matricule_personnel)

    def test_creation_persiste_le_motif_et_rafraichit_l_agenda_et_les_statistiques(self):
        date_rdv = timezone.localdate() + datetime.timedelta(days=1)
        response = self.client.post(
            "/api/soins/rendez-vous/",
            {
                "id_patient": str(self.patient_a.pk),
                "matricule_personnel": str(self.medecin_a.pk),
                "date_rendez_vous": date_rdv.isoformat(),
                "heure_rendez_vous": "10:00",
                "motif": "Consultation de controle",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["motif"], "Consultation de controle")
        self.assertEqual(response.data["patient"], {"nom": "Alpha", "prenom": "Jean"})
        self.assertEqual(response.data["medecin"]["nom"], "Nom")
        rendez_vous = RendezVous.objects.get(pk=response.data["id_rdv"])
        self.assertEqual(rendez_vous.id_etablissement_id, self.hopital_a.pk)
        self.assertEqual(rendez_vous.motif, "Consultation de controle")

        agenda = self.client.get("/api/soins/rendez-vous/")
        self.assertEqual(agenda.status_code, 200)
        self.assertTrue(any(item["id_rdv"] == str(rendez_vous.pk) for item in agenda.data))

        statistiques = self.client.get("/api/statistiques/")
        self.assertEqual(statistiques.status_code, 200)
        self.assertGreaterEqual(statistiques.data["soins"]["rendez_vous_a_venir"], 1)




class RendezVousAnnulationRG07Tests(BaseBloc3):
    def rdv_futur(self):
        debut = timezone.localtime(timezone.now()) + datetime.timedelta(days=2)
        debut = debut.replace(second=0, microsecond=0)
        rdv = RendezVous.objects.create(
            date_rendez_vous=debut.date(),
            heure_rendez_vous=debut.time().replace(tzinfo=None),
            id_patient=self.patient_a2,
            matricule_personnel=self.medecin_a,
            id_etablissement=self.hopital_a,
        )
        return rdv, debut

    def test_exactement_deux_heures_avant_est_une_annulation_normale(self):
        rdv, debut = self.rdv_futur()
        rdv.annuler(maintenant=debut - datetime.timedelta(hours=2))
        self.assertEqual(rdv.statut_rendez_vous, RendezVous.ANNULE)

    def test_moins_de_deux_heures_avant_devient_absent(self):
        rdv, debut = self.rdv_futur()
        rdv.annuler(maintenant=debut - datetime.timedelta(hours=1, minutes=59))
        self.assertEqual(rdv.statut_rendez_vous, RendezVous.ABSENT)

    def test_apres_le_creneau_devient_absent(self):
        rdv, debut = self.rdv_futur()
        rdv.annuler(maintenant=debut + datetime.timedelta(minutes=1))
        self.assertEqual(rdv.statut_rendez_vous, RendezVous.ABSENT)


class ActeEtConsultationTests(BaseBloc3):
    def test_montant_negatif_refuse_par_save_et_par_la_base(self):
        with self.assertRaises(ValidationError):
            creer_acte(self.hopital_a, self.patient_a, montant="-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Acte.objects.bulk_create(
                [Acte(date_acte=JOUR, libelle_acte="X", montant_base=Decimal("-1"), id_patient=self.patient_a,
                      id_etablissement=self.hopital_a)]
            )

    def test_une_consultation_peut_exister_sans_rendez_vous(self):
        consultation = creer_consultation(self.hopital_a, self.patient_a2, self.medecin_a)
        self.assertIsNone(consultation.id_rendez_vous_id)
        self.assertEqual(consultation.statut_episode, Consultation.EN_COURS)

    def test_l_interne_est_valide_par_son_superviseur_rg10(self):
        creer_consultation(self.hopital_a, self.patient_a2, self.medecin_a, matricule_interne=self.interne_a)

    def test_l_interne_ne_peut_pas_etre_le_medecin_qui_signe(self):
        with self.assertRaises(ValidationError):
            creer_consultation(self.hopital_a, self.patient_a2, self.medecin_a, matricule_interne=self.medecin_a)

    def test_le_medecin_qui_signe_doit_etre_le_superviseur_de_l_interne(self):
        autre = creer_medecin(self.hopital_a, "dr_autre")
        with self.assertRaises(ValidationError):
            creer_consultation(self.hopital_a, self.patient_a2, autre, matricule_interne=self.interne_a)

    def test_episode_clos_exige_une_date_de_cloture_et_inversement(self):
        with self.assertRaises(ValidationError):
            creer_consultation(self.hopital_a, self.patient_a2, self.medecin_a, statut_episode=Consultation.CLOS)
        maintenant = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.timezone.utc)
        with self.assertRaises(ValidationError):
            creer_consultation(self.hopital_a, self.patient_a2, self.medecin_a, date_cloture_episode=maintenant)
        creer_consultation(
            self.hopital_a, self.patient_a2, self.medecin_a,
            statut_episode=Consultation.CLOS, date_cloture_episode=maintenant,
        )

    def test_le_rendez_vous_doit_concerner_le_meme_patient(self):
        with self.assertRaises(ValidationError):
            # Le rendez-vous du parcours A concerne patient_a, la consultation patient_a2.
            creer_consultation(
                self.hopital_a, self.patient_a2, self.medecin_a, id_rendez_vous=self.parcours_a["rdv"]
            )

    def test_la_consultation_doit_etre_du_meme_etablissement_que_son_acte(self):
        acte = creer_acte(self.hopital_a, self.patient_a2, "Consultation")
        with self.assertRaises(ValidationError):
            Consultation.objects.create(
                id_acte=acte, diagnostic="X", matricule_personnel=self.medecin_a, id_etablissement=self.hopital_b
            )



class ChambresLitsEtHospitalisationsTests(BaseBloc3):
    def nouvelle_consultation(self):
        return creer_consultation(self.hopital_a, self.patient_a2, self.medecin_a)

    def test_numero_de_chambre_unique_par_etablissement(self):
        with self.assertRaises(ValidationError):
            Chambre.objects.create(
                numero_chambre="101", code_service=self.parcours_a["service"], id_etablissement=self.hopital_a
            )

    def test_numero_de_lit_unique_par_chambre_mais_reutilisable_ailleurs(self):
        with self.assertRaises(ValidationError):
            Lit.objects.create(numero_lit="1", id_chambre=self.parcours_a["chambre"], id_etablissement=self.hopital_a)
        autre = Chambre.objects.create(
            numero_chambre="102", code_service=self.parcours_a["service"], id_etablissement=self.hopital_a
        )
        Lit.objects.create(numero_lit="1", id_chambre=autre, id_etablissement=self.hopital_a)

    def test_un_lit_n_accueille_qu_un_patient_a_la_fois_rg13(self):
        with self.assertRaises(ValidationError):
            creer_hospitalisation(
                self.hopital_a, self.patient_a2, self.nouvelle_consultation(),
                id_chambre=self.parcours_a["chambre"], id_lit=self.parcours_a["lit"],
            )

    def test_la_base_refuse_aussi_un_lit_double_rg13(self):
        consultation = self.nouvelle_consultation()
        acte = creer_acte(self.hopital_a, self.patient_a2, "Hospitalisation")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Hospitalisation.objects.bulk_create(
                [
                    Hospitalisation(
                        id_acte=acte, date_entree=JOUR, id_acte_consultation=consultation,
                        id_chambre=self.parcours_a["chambre"], id_lit=self.parcours_a["lit"],
                        id_etablissement=self.hopital_a,
                    )
                ]
            )

    def test_le_lit_se_libere_a_la_sortie_et_l_historique_est_conserve(self):
        premiere = self.parcours_a["hospitalisation"]
        premiere.date_sortie = JOUR + datetime.timedelta(days=3)
        premiere.save()
        creer_hospitalisation(
            self.hopital_a, self.patient_a2, self.nouvelle_consultation(),
            id_chambre=self.parcours_a["chambre"], id_lit=self.parcours_a["lit"],
        )
        self.assertEqual(Hospitalisation.objects.filter(id_lit=self.parcours_a["lit"]).count(), 2)

    def test_hospitalisation_en_attente_sans_lit_acceptee_rg14(self):
        hospitalisation = creer_hospitalisation(self.hopital_a, self.patient_a2, self.nouvelle_consultation())
        self.assertIsNone(hospitalisation.id_lit_id)
        self.assertIsNone(hospitalisation.id_chambre_id)

    def test_une_consultation_ne_decide_qu_une_hospitalisation(self):
        with self.assertRaises(ValidationError):
            creer_hospitalisation(self.hopital_a, self.patient_a, self.parcours_a["consultation"])

    def test_un_lit_exige_sa_chambre(self):
        with self.assertRaises(ValidationError):
            creer_hospitalisation(
                self.hopital_a, self.patient_a2, self.nouvelle_consultation(), id_lit=self.parcours_a["lit"]
            )

    def test_le_lit_doit_appartenir_a_la_chambre_indiquee(self):
        autre = Chambre.objects.create(
            numero_chambre="102", code_service=self.parcours_a["service"], id_etablissement=self.hopital_a
        )
        with self.assertRaises(ValidationError):
            creer_hospitalisation(
                self.hopital_a, self.patient_a2, self.nouvelle_consultation(),
                id_chambre=autre, id_lit=self.parcours_a["lit"],
            )

    def test_la_sortie_ne_peut_pas_preceder_l_entree(self):
        with self.assertRaises(ValidationError):
            creer_hospitalisation(
                self.hopital_a, self.patient_a2, self.nouvelle_consultation(),
                date_sortie=JOUR - datetime.timedelta(days=1),
            )

    def test_l_hospitalisation_concerne_le_patient_de_la_consultation(self):
        consultation = self.nouvelle_consultation()  # consultation de patient_a2
        with self.assertRaises(ValidationError):
            creer_hospitalisation(self.hopital_a, self.patient_a, consultation)

    def test_sans_etablissement_validation_error_et_clean_ne_plante_pas(self):
        for instance in (
            Chambre(numero_chambre="X"),
            Lit(numero_lit="X"),
            Hospitalisation(date_entree=JOUR),
            Consultation(diagnostic="X"),
            Acte(libelle_acte="X", date_acte=JOUR, montant_base=Decimal("1")),
        ):
            instance.clean()
        with self.assertRaises(ValidationError) as cm:
            Chambre(numero_chambre="X", code_service=self.parcours_a["service"]).save()
        self.assertIn("id_etablissement", cm.exception.message_dict)
