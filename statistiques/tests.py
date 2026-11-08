import datetime

from django.test import TestCase
from rest_framework.test import APIClient

from etablissements.models import Etablissement, Personnel


class TableauDeBordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hopital = Etablissement.objects.create(
            nom_etablissement="Hôpital statistiques",
            type_etablissement=Etablissement.TYPE_HOPITAL,
            adresse="Bujumbura",
            telephone_contact="+25779000000",
        )
        cls.admin = Personnel.objects.create_user(
            identifiant_connexion="admin_stats_test",
            email_professionnel="admin_stats_test@example.org",
            password="test",
            nom="Admin",
            prenom="Stats",
            role_metier="administrateur",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )
        cls.comptable = Personnel.objects.create_user(
            identifiant_connexion="comptable_stats_test",
            email_professionnel="comptable_stats_test@example.org",
            password="test",
            nom="Comptable",
            prenom="Stats",
            role_metier="comptable",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )

    def setUp(self):
        self.client = APIClient()

    def test_administrateur_recoit_les_domaines_agreges_et_la_periode(self):
        self.client.force_login(self.admin)
        response = self.client.get("/api/statistiques/", {"date_debut": "2026-11-01", "date_fin": "2026-11-07"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {"soins", "pharmacie", "laboratoire", "facturation"},
            set(response.data) - {"date_debut", "date_fin"},
        )
        self.assertEqual(response.data["date_debut"], datetime.date(2026, 11, 1))

    def test_comptable_ne_recoit_que_les_statistiques_de_facturation(self):
        self.client.force_login(self.comptable)
        response = self.client.get("/api/statistiques/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("facturation", response.data)
        self.assertNotIn("soins", response.data)
        self.assertNotIn("pharmacie", response.data)

    def test_periode_inversee_est_refusee(self):
        self.client.force_login(self.admin)
        response = self.client.get("/api/statistiques/", {"date_debut": "2026-11-08", "date_fin": "2026-11-07"})
        self.assertEqual(response.status_code, 400)
