import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from etablissements.models import Etablissement, Hopital, Personnel, Pharmacie, Service


class EtablissementModelTests(TestCase):
    def etablissement(self, nom, type_etablissement):
        return Etablissement.objects.create(
            nom_etablissement=nom,
            type_etablissement=type_etablissement,
            adresse="Bujumbura",
            telephone_contact="+25779000000",
        )

    def test_un_hopital_exige_un_etablissement_de_type_hopital(self):
        pharmacie = self.etablissement("Pharmacie", Etablissement.TYPE_PHARMACIE)
        with self.assertRaises(ValidationError):
            Hopital(id_etablissement=pharmacie, numero_agrement="H-1").clean()

    def test_une_pharmacie_exige_un_etablissement_de_type_pharmacie(self):
        hopital = self.etablissement("Hôpital", Etablissement.TYPE_HOPITAL)
        with self.assertRaises(ValidationError):
            Pharmacie(id_etablissement=hopital, numero_agrement_pharmaceutique="P-1").clean()

    def test_service_est_reserve_a_un_hopital(self):
        pharmacie = self.etablissement("Pharmacie", Etablissement.TYPE_PHARMACIE)
        with self.assertRaises(ValidationError):
            Service(nom_service="Consultation", id_etablissement=pharmacie).clean()

    def test_compte_personnel_stocke_un_hash_de_mot_de_passe(self):
        etablissement = self.etablissement("Hôpital", Etablissement.TYPE_HOPITAL)
        personnel = Personnel.objects.create_user(
            identifiant_connexion="agent_test",
            email_professionnel="agent_test@example.org",
            password="un-mot-de-passe",
            nom="Test",
            prenom="Agent",
            role_metier="secretaire",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=etablissement,
        )
        self.assertNotEqual(personnel.password, "un-mot-de-passe")
        self.assertTrue(personnel.check_password("un-mot-de-passe"))
