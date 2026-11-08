import datetime

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import RLSTestCase
from etablissements.models import Etablissement, Personnel
from partenariats.models import Partenariat


def creer_etablissement(nom):
    return Etablissement.objects.create(
        nom_etablissement=nom,
        type_etablissement=Etablissement.TYPE_HOPITAL,
        adresse="Gitega",
        telephone_contact="+25779000000",
    )


def creer_admin(etablissement, identifiant):
    return Personnel.objects.create_user(
        identifiant_connexion=identifiant,
        email_professionnel=f"{identifiant}@example.org",
        password="test",
        nom="Admin",
        prenom=identifiant,
        role_metier="administrateur",
        date_embauche=datetime.date(2026, 1, 1),
        role_acces="standard",
        id_etablissement=etablissement,
    )


class PartenariatTests(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.etab_a = creer_etablissement("Hôpital A")
        cls.etab_b = creer_etablissement("Hôpital B")
        cls.etab_c = creer_etablissement("Hôpital C")
        cls.admin_a = creer_admin(cls.etab_a, "admin_part_a")
        cls.admin_b = creer_admin(cls.etab_b, "admin_part_b")

    def proposer(self):
        self.positionner(self.etab_a.pk)
        return Partenariat.objects.create(
            id_etablissement=self.etab_a,
            id_etablissement_partenaire=self.etab_b,
            type_partenariat="laboratoire_externe",
            date_debut=datetime.date(2026, 11, 7),
            description="Analyses spécialisées",
            matricule_proposant=self.admin_a,
        )

    def test_proposition_est_en_attente_jusqua_validation_du_partenaire(self):
        partenariat = self.proposer()
        self.assertEqual(partenariat.statut, Partenariat.EN_ATTENTE)
        self.assertIsNone(partenariat.matricule_validateur_id)

    def test_les_deux_etablissements_voient_le_partenariat_et_le_troisieme_non(self):
        partenariat = self.proposer()
        for etablissement in (self.etab_a, self.etab_b):
            with self.session(etablissement):
                self.assertTrue(Partenariat.objects.filter(pk=partenariat.pk).exists())
        with self.session(self.etab_c):
            self.assertFalse(Partenariat.objects.filter(pk=partenariat.pk).exists())

    def test_insertion_par_un_tenant_non_initiateur_est_bloquee_par_rls(self):
        with self.session(self.etab_b), self.assertRaises(DatabaseError), transaction.atomic():
            Partenariat.objects.create(
                id_etablissement=self.etab_a,
                id_etablissement_partenaire=self.etab_b,
                type_partenariat="autre",
                date_debut=datetime.date(2026, 11, 7),
                matricule_proposant=self.admin_a,
            )

    def test_un_etablissement_ne_peut_pas_etre_partenaire_de_lui_meme(self):
        self.positionner(self.etab_a.pk)
        with self.assertRaises(ValidationError):
            Partenariat.objects.create(
                id_etablissement=self.etab_a,
                id_etablissement_partenaire=self.etab_a,
                type_partenariat="autre",
                matricule_proposant=self.admin_a,
            )

    def test_proposition_requiert_un_administrateur_de_l_etablissement_initiateur(self):
        personnel = Personnel.objects.create_user(
            identifiant_connexion="infirm_part",
            email_professionnel="infirm_part@example.org",
            password="test",
            nom="Infirmier",
            prenom="Un",
            role_metier="infirmier",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=self.etab_a,
        )
        self.positionner(self.etab_a.pk)
        with self.assertRaises(ValidationError):
            Partenariat.objects.create(
                id_etablissement=self.etab_a,
                id_etablissement_partenaire=self.etab_b,
                type_partenariat="autre",
                matricule_proposant=personnel,
            )


class PartenariatApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.etab_a = creer_etablissement("Hôpital API A")
        cls.etab_b = creer_etablissement("Hôpital API B")
        cls.admin_a = creer_admin(cls.etab_a, "admin_api_a")
        cls.admin_b = creer_admin(cls.etab_b, "admin_api_b")

    def test_activation_exige_la_reponse_de_l_etablissement_partenaire(self):
        client = APIClient()
        client.force_login(self.admin_a)
        response = client.post(
            "/api/partenariats/",
            {
                "id_etablissement_partenaire": str(self.etab_b.pk),
                "type_partenariat": "laboratoire_externe",
                "date_debut": "2026-11-07",
                "description": "Analyses spécialisées",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        id_partenariat = response.data["id_partenariat"]
        self.assertEqual(response.data["statut"], Partenariat.EN_ATTENTE)

        tentative_initiateur = client.post(
            f"/api/partenariats/{id_partenariat}/repondre/", {"action": "accepter"}, format="json"
        )
        self.assertEqual(tentative_initiateur.status_code, 403)

        client.force_login(self.admin_b)
        reponse = client.post(
            f"/api/partenariats/{id_partenariat}/repondre/", {"action": "accepter"}, format="json"
        )
        self.assertEqual(reponse.status_code, 200, reponse.data)
        self.assertEqual(reponse.data["statut"], Partenariat.ACTIF)
        self.assertEqual(reponse.data["matricule_validateur"], str(self.admin_b.pk))

    def test_un_doublon_inverse_est_refuse_pendant_que_la_proposition_est_en_attente(self):
        client = APIClient()
        client.force_login(self.admin_a)
        reponse = client.post(
            "/api/partenariats/",
            {"id_etablissement_partenaire": str(self.etab_b.pk), "type_partenariat": "laboratoire_externe"},
            format="json",
        )
        self.assertEqual(reponse.status_code, 201, reponse.data)
        client.force_login(self.admin_b)
        reponse_inverse = client.post(
            "/api/partenariats/",
            {"id_etablissement_partenaire": str(self.etab_a.pk), "type_partenariat": "laboratoire_externe"},
            format="json",
        )
        self.assertEqual(reponse_inverse.status_code, 400)

    def test_un_non_administrateur_ne_peut_pas_proposer_un_partenariat(self):
        agent = Personnel.objects.create_user(
            identifiant_connexion="agent_api_part",
            email_professionnel="agent_api_part@example.org",
            password="test",
            nom="Agent",
            prenom="A",
            role_metier="secretaire",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=self.etab_a,
        )
        client = APIClient()
        client.force_login(agent)
        response = client.post(
            "/api/partenariats/",
            {"id_etablissement_partenaire": str(self.etab_b.pk), "type_partenariat": "autre"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
