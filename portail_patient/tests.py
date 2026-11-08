import datetime

from django.test import Client, TestCase
from django.utils import timezone

from core.testing import RLSTestCase
from etablissements.models import Etablissement, Medecin, Personnel
from facturation.models import Facture
from patients.models import Patient, Telephone
from portail_patient.documents import generer_pdf
from portail_patient.models import AccesDocumentPatient
from portail_patient.services import PortailPatientError, demander_code, verifier_code
from soins.models import Acte, Consultation


class PortailPatientServiceTests(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hopital = Etablissement.objects.create(
            nom_etablissement="Hôpital portail",
            type_etablissement=Etablissement.TYPE_HOPITAL,
            adresse="Gitega",
            telephone_contact="+25779000000",
        )
        cls.positionner(cls.hopital.pk)
        cls.patient = Patient.objects.create(
            nom_patient="Nkurunziza",
            prenom_patient="Aline",
            date_naissance=datetime.date(1990, 5, 17),
            sexe="F",
            id_etablissement=cls.hopital,
        )
        Telephone.objects.create(
            numero_telephone="+25779000001",
            type_telephone="mobile",
            id_patient=cls.patient,
            id_etablissement=cls.hopital,
        )

    def setUp(self):
        self.positionner(self.hopital.pk)

    def test_code_temporaire_est_unique_et_utilisable_une_seule_fois(self):
        with self.session(self.hopital):
            code = demander_code(id_hopital=self.hopital.pk, numero_telephone="+25779000001")
            patient = verifier_code(
                id_hopital=self.hopital.pk,
                numero_telephone="+25779000001",
                code=code["code"],
            )
        self.assertEqual(patient.pk, self.patient.pk)
        with self.session(self.hopital), self.assertRaises(PortailPatientError):
            verifier_code(
                id_hopital=self.hopital.pk,
                numero_telephone="+25779000001",
                code=code["code"],
            )

    def test_nouveau_code_invalide_le_precedent(self):
        with self.session(self.hopital):
            premier = demander_code(id_hopital=self.hopital.pk, numero_telephone="+25779000001")
            second = demander_code(id_hopital=self.hopital.pk, numero_telephone="+25779000001")
            with self.assertRaises(PortailPatientError):
                verifier_code(
                    id_hopital=self.hopital.pk,
                    numero_telephone="+25779000001",
                    code=premier["code"],
                )
            patient = verifier_code(
                id_hopital=self.hopital.pk,
                numero_telephone="+25779000001",
                code=second["code"],
            )
        self.assertEqual(patient.pk, self.patient.pk)

    def test_pdf_est_genere_en_memoire_avec_entete_pdf(self):
        fichier = generer_pdf("Résultat d'examen", ["Patient : Aline Nkurunziza", "Résultat normal"])
        self.assertTrue(fichier.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", fichier)


class DocumentsPatientPermissionsTests(TestCase):
    def test_documents_refuse_sans_session_patient(self):
        response = Client().get("/api/portail/documents/")
        self.assertEqual(response.status_code, 403)


class DocumentsPatientAccesTests(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hopital = Etablissement.objects.create(
            nom_etablissement="Hôpital documents",
            type_etablissement=Etablissement.TYPE_HOPITAL,
            adresse="Gitega",
            telephone_contact="+25779000000",
        )
        cls.medecin_personnel = Personnel.objects.create_user(
            identifiant_connexion="medecin_documents_test",
            email_professionnel="medecin_documents_test@example.org",
            password="test",
            nom="Médecin",
            prenom="Aline",
            role_metier="medecin",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )
        cls.medecin = Medecin.objects.create(matricule_personnel=cls.medecin_personnel, specialite="Générale")
        cls.positionner(cls.hopital.pk)
        cls.patient_a = Patient.objects.create(
            nom_patient="Nkurunziza",
            prenom_patient="Aline",
            date_naissance=datetime.date(1990, 5, 17),
            sexe="F",
            id_etablissement=cls.hopital,
        )
        cls.patient_b = Patient.objects.create(
            nom_patient="Niyonzima",
            prenom_patient="Paul",
            date_naissance=datetime.date(1988, 2, 1),
            sexe="M",
            id_etablissement=cls.hopital,
        )
        acte = Acte.objects.create(
            date_acte=datetime.date(2026, 11, 7),
            libelle_acte="Consultation",
            montant_base="100.00",
            id_patient=cls.patient_a,
            id_etablissement=cls.hopital,
        )
        consultation = Consultation.objects.create(
            id_acte=acte,
            diagnostic="Consultation générale",
            matricule_personnel=cls.medecin,
            statut_episode=Consultation.CLOS,
            date_cloture_episode=timezone.now(),
            id_etablissement=cls.hopital,
        )
        cls.facture = Facture.objects.create(
            id_patient=cls.patient_a,
            id_acte_consultation=consultation,
            statut_facture=Facture.EMISE,
            id_etablissement=cls.hopital,
        )

    def setUp(self):
        self.positionner(self.hopital.pk)

    def portail_client(self, patient):
        client = Client()
        session = client.session
        session["portail_patient_id"] = str(patient.pk)
        session["portail_hopital_id"] = str(self.hopital.pk)
        session.save()
        return client

    def test_patient_peut_telecharger_sa_facture_et_acces_est_journalise(self):
        client = self.portail_client(self.patient_a)
        with self.session(self.hopital):
            response = client.get(
                f"/api/portail/documents/facture/{self.facture.pk}/telecharger/"
            )
            contenu = b"".join(response.streaming_content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(contenu.startswith(b"%PDF-1.4"))
        self.assertTrue(
            AccesDocumentPatient.objects.filter(
                id_patient=self.patient_a,
                id_document=self.facture.pk,
                action=AccesDocumentPatient.TELECHARGEMENT,
            ).exists()
        )

    def test_patient_ne_peut_pas_telecharger_la_facture_d_un_autre_patient(self):
        client = self.portail_client(self.patient_b)
        with self.session(self.hopital):
            response = client.get(
                f"/api/portail/documents/facture/{self.facture.pk}/telecharger/"
            )
        self.assertEqual(response.status_code, 404)
