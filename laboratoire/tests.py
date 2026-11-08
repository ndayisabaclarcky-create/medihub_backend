import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError

from core.testing import RLSTestCase
from etablissements.models import Etablissement, Medecin, Personnel
from laboratoire.models import Examen, Notification, ResultatExamen
from laboratoire.services import enregistrer_resultat, prescrire_examens
from patients.models import Patient
from soins.models import Acte, Consultation


class LaboratoireServiceTests(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hopital = Etablissement.objects.create(
            nom_etablissement="Hôpital laboratoire",
            type_etablissement=Etablissement.TYPE_HOPITAL,
            adresse="Gitega",
            telephone_contact="+25779000000",
        )
        cls.medecin_personnel = Personnel.objects.create_user(
            identifiant_connexion="medecin_labo_test",
            email_professionnel="medecin_labo_test@example.org",
            password="test",
            nom="Médecin",
            prenom="Marie",
            role_metier="medecin",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )
        cls.medecin = Medecin.objects.create(matricule_personnel=cls.medecin_personnel, specialite="Générale")
        cls.technicien = Personnel.objects.create_user(
            identifiant_connexion="technicien_labo_test",
            email_professionnel="technicien_labo_test@example.org",
            password="test",
            nom="Technicien",
            prenom="Paul",
            role_metier="technicien_labo",
            date_embauche=datetime.date(2026, 1, 1),
            role_acces="standard",
            id_etablissement=cls.hopital,
        )
        cls.positionner(cls.hopital.pk)
        cls.patient = Patient.objects.create(
            nom_patient="Ndayizeye",
            prenom_patient="Aline",
            date_naissance=datetime.date(1990, 5, 17),
            sexe="F",
            id_etablissement=cls.hopital,
        )
        cls.acte_consultation = Acte.objects.create(
            date_acte=datetime.date(2026, 11, 7),
            libelle_acte="Consultation",
            montant_base=Decimal("20.00"),
            id_patient=cls.patient,
            id_etablissement=cls.hopital,
        )
        cls.consultation = Consultation.objects.create(
            id_acte=cls.acte_consultation,
            diagnostic="Fièvre",
            matricule_personnel=cls.medecin,
            id_etablissement=cls.hopital,
        )
        cls.examen = Examen.objects.create(
            code_examen="HEMO",
            libelle_examen="Hémogramme",
            tarif=Decimal("10.00"),
            id_etablissement=cls.hopital,
        )

    def setUp(self):
        self.positionner(self.hopital.pk)

    def prescrire(self):
        with self.session(self.hopital):
            examens, indisponibles = prescrire_examens(
                id_hopital=self.hopital.pk,
                matricule_medecin=self.medecin.pk,
                id_consultation=self.consultation.pk,
                codes_examens=["HEMO", "IRM-EXT"],
            )
        return examens, indisponibles

    def test_prescription_cree_les_examens_disponibles_et_retourne_les_absents(self):
        examens, indisponibles = self.prescrire()
        self.assertEqual(len(examens), 1)
        self.assertEqual(indisponibles, ["IRM-EXT"])
        self.assertEqual(examens[0].id_acte.id_patient_id, self.patient.pk)

    def test_examen_absent_du_catalogue_n_est_pas_enregistre(self):
        with self.session(self.hopital):
            examens, indisponibles = prescrire_examens(
                id_hopital=self.hopital.pk,
                matricule_medecin=self.medecin.pk,
                id_consultation=self.consultation.pk,
                codes_examens=["INCONNU"],
            )
        self.assertEqual(examens, [])
        self.assertEqual(indisponibles, ["INCONNU"])

    def test_une_consultation_cloturee_ne_peut_pas_recevoir_un_examen(self):
        self.consultation.statut_episode = Consultation.CLOS
        self.consultation.date_cloture_episode = datetime.datetime(2026, 11, 7, 12, tzinfo=datetime.timezone.utc)
        self.consultation.save()
        with self.session(self.hopital), self.assertRaises(ValidationError):
            prescrire_examens(
                id_hopital=self.hopital.pk,
                matricule_medecin=self.medecin.pk,
                id_consultation=self.consultation.pk,
                codes_examens=["HEMO"],
            )

    def test_resultat_cree_notification_et_ne_peut_etre_enregistre_deux_fois(self):
        examens, _ = self.prescrire()
        with self.session(self.hopital):
            resultat = enregistrer_resultat(
                id_hopital=self.hopital.pk,
                id_acte_examen=examens[0].pk,
                matricule_technicien=self.technicien.pk,
                contenu_resultat="Résultat normal",
            )
            self.assertTrue(Notification.objects.filter(id_resultat_examen=resultat).exists())
            self.assertEqual(ResultatExamen.objects.count(), 1)
            with self.assertRaises(ValidationError):
                enregistrer_resultat(
                    id_hopital=self.hopital.pk,
                    id_acte_examen=examens[0].pk,
                    matricule_technicien=self.technicien.pk,
                    contenu_resultat="Deuxième résultat",
                )
