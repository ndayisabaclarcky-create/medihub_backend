import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.testing import RLSTestCase
from etablissements.models import Etablissement, Medecin, Personnel
from facturation.models import Facture
from facturation.services import enregistrer_paiement, generer_facture
from patients.models import Patient
from soins.models import Acte, Consultation


class FacturationServiceTests(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hopital = Etablissement.objects.create(
            nom_etablissement="Hôpital facturation",
            type_etablissement=Etablissement.TYPE_HOPITAL,
            adresse="Gitega",
            telephone_contact="+25779000000",
        )
        cls.comptable = Personnel.objects.create_user(
            identifiant_connexion="comptable_facture_test",
            email_professionnel="comptable_facture_test@example.org",
            password="test",
            nom="Comptable",
            prenom="Jean",
            role_metier="comptable",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )
        medecin_personnel = Personnel.objects.create_user(
            identifiant_connexion="medecin_facture_test",
            email_professionnel="medecin_facture_test@example.org",
            password="test",
            nom="Médecin",
            prenom="Jean",
            role_metier="medecin",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )
        cls.medecin = Medecin.objects.create(matricule_personnel=medecin_personnel, specialite="Générale")
        cls.positionner(cls.hopital.pk)
        cls.patient = Patient.objects.create(
            nom_patient="Nkurunziza",
            prenom_patient="Aline",
            date_naissance=datetime.date(1990, 5, 17),
            sexe="F",
            id_etablissement=cls.hopital,
        )
        cls.acte = Acte.objects.create(
            date_acte=datetime.date(2026, 11, 7),
            libelle_acte="Consultation",
            montant_base=Decimal("100.00"),
            id_patient=cls.patient,
            id_etablissement=cls.hopital,
        )
        cls.consultation = Consultation.objects.create(
            id_acte=cls.acte,
            diagnostic="Paludisme",
            matricule_personnel=cls.medecin,
            statut_episode=Consultation.CLOS,
            date_cloture_episode=timezone.now(),
            id_etablissement=cls.hopital,
        )

    def setUp(self):
        self.positionner(self.hopital.pk)

    def emettre(self):
        with self.session(self.hopital):
            return generer_facture(
                id_hopital=self.hopital.pk,
                id_acte_consultation=self.consultation.pk,
                matricule_personnel=self.comptable.pk,
            )

    def test_facture_unique_d_episode_avec_total_des_actes(self):
        facture = self.emettre()
        self.assertEqual(facture.montant_total, Decimal("100.00"))
        with self.session(self.hopital), self.assertRaises(ValidationError):
            generer_facture(
                id_hopital=self.hopital.pk,
                id_acte_consultation=self.consultation.pk,
                matricule_personnel=self.comptable.pk,
            )

    def test_paiements_partiels_et_solde_final(self):
        facture = self.emettre()
        with self.session(self.hopital):
            enregistrer_paiement(
                id_hopital=self.hopital.pk,
                id_facture=facture.pk,
                matricule_personnel=self.comptable.pk,
                montant_paye="35.00",
            )
            facture.refresh_from_db()
            self.assertEqual(facture.statut_facture, Facture.PARTIELLEMENT_PAYEE)
            enregistrer_paiement(
                id_hopital=self.hopital.pk,
                id_facture=facture.pk,
                matricule_personnel=self.comptable.pk,
                montant_paye="65.00",
            )
            facture.refresh_from_db()
            self.assertEqual(facture.statut_facture, Facture.SOLDEE)
            self.assertEqual(facture.solde_patient, Decimal("0.00"))

    def test_paiement_superieur_au_solde_est_refuse(self):
        facture = self.emettre()
        with self.session(self.hopital), self.assertRaises(ValidationError):
            enregistrer_paiement(
                id_hopital=self.hopital.pk,
                id_facture=facture.pk,
                matricule_personnel=self.comptable.pk,
                montant_paye="100.01",
            )
