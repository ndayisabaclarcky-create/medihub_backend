import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import RLSTestCase
from etablissements.models import Etablissement, Personnel, Service
from equipements.models import Equipement, InterventionMaintenance


def creer_etablissement(nom):
    return Etablissement.objects.create(
        nom_etablissement=nom,
        type_etablissement=Etablissement.TYPE_HOPITAL,
        adresse="Bujumbura",
        telephone_contact="+25779000000",
    )


class EquipementsTests(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.etab_a = creer_etablissement("Hôpital équipement A")
        cls.etab_b = creer_etablissement("Hôpital équipement B")
        cls.personnel = Personnel.objects.create_user(
            identifiant_connexion="tech_equipement",
            email_professionnel="tech_equipement@example.org",
            password="test",
            nom="Technicien",
            prenom="A",
            role_metier="technicien_labo",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.etab_a,
        )
        cls.positionner(cls.etab_a.pk)
        cls.service_a = Service.objects.create(nom_service="Laboratoire", id_etablissement=cls.etab_a)
        cls.equipement_a = Equipement.objects.create(
            code_equipement="EQ-001",
            nom="Microscope",
            categorie="laboratoire",
            emplacement="Salle A",
            code_service=cls.service_a,
            id_etablissement=cls.etab_a,
        )

    def setUp(self):
        self.positionner(self.etab_a.pk)

    def test_equipement_et_interventions_sont_isoles_par_rls(self):
        InterventionMaintenance.objects.create(
            id_equipement=self.equipement_a,
            type_intervention=InterventionMaintenance.PREVENTIVE,
            date_planifiee=datetime.date(2026, 11, 8),
            description="Vérification annuelle",
            cout=Decimal("25.00"),
            matricule_technicien=self.personnel,
            prochaine_echeance=datetime.date(2027, 11, 8),
            id_etablissement=self.etab_a,
        )
        with self.session(self.etab_a):
            self.assertEqual(Equipement.objects.count(), 1)
            self.assertEqual(InterventionMaintenance.objects.count(), 1)
        with self.session(self.etab_b):
            self.assertEqual(Equipement.objects.count(), 0)
            self.assertEqual(InterventionMaintenance.objects.count(), 0)

    def test_un_code_equipement_est_unique_dans_un_etablissement(self):
        with self.assertRaises(ValidationError):
            Equipement.objects.create(
                code_equipement="EQ-001",
                nom="Autre appareil",
                categorie="soins",
                emplacement="Salle B",
                id_etablissement=self.etab_a,
            )

    def test_intervention_refuse_un_equipement_d_un_autre_etablissement(self):
        self.positionner(self.etab_b.pk)
        equipement_b = Equipement.objects.create(
            code_equipement="EQ-002",
            nom="Appareil B",
            categorie="soins",
            emplacement="Salle B",
            id_etablissement=self.etab_b,
        )
        with self.assertRaises(ValidationError):
            InterventionMaintenance.objects.create(
                id_equipement=equipement_b,
                type_intervention=InterventionMaintenance.CORRECTIVE,
                date_planifiee=datetime.date(2026, 11, 8),
                description="Réparation",
                id_etablissement=self.etab_a,
            )

    def test_cout_negatif_est_refuse(self):
        with self.assertRaises(ValidationError):
            InterventionMaintenance.objects.create(
                id_equipement=self.equipement_a,
                type_intervention=InterventionMaintenance.CORRECTIVE,
                date_planifiee=datetime.date(2026, 11, 8),
                description="Réparation",
                cout=Decimal("-1.00"),
                id_etablissement=self.etab_a,
            )


class EquipementsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hopital = creer_etablissement("Hôpital équipement API")
        cls.admin = Personnel.objects.create_user(
            identifiant_connexion="admin_equipement_api",
            email_professionnel="admin_equipement_api@example.org",
            password="test",
            nom="Admin",
            prenom="A",
            role_metier="administrateur",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )
        cls.agent = Personnel.objects.create_user(
            identifiant_connexion="agent_equipement_api",
            email_professionnel="agent_equipement_api@example.org",
            password="test",
            nom="Agent",
            prenom="B",
            role_metier="infirmier",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )

    def test_administrateur_cree_un_equipement_et_un_agent_ne_peut_pas_l_ecrire(self):
        client = APIClient()
        client.force_login(self.admin)
        response = client.post(
            "/api/equipements/equipements/",
            {
                "code_equipement": "EQ-API-1",
                "nom": "Échographe",
                "categorie": "imagerie",
                "emplacement": "Salle 1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["id_etablissement"], str(self.hopital.pk))
        doublon = client.post(
            "/api/equipements/equipements/",
            {
                "code_equipement": "EQ-API-1",
                "nom": "Autre échographe",
                "categorie": "imagerie",
                "emplacement": "Salle 2",
            },
            format="json",
        )
        self.assertEqual(doublon.status_code, 400)
        client.force_login(self.agent)
        response = client.post(
            "/api/equipements/equipements/",
            {
                "code_equipement": "EQ-API-2",
                "nom": "Moniteur",
                "categorie": "soins",
                "emplacement": "Salle 2",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
