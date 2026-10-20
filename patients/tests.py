"""
Tests du Bloc 2 : isolation RLS, rapprochement / partage de dossier (RG35-RG37),
contraintes et validations.

Les données sont créées avec la variable de session positionnée sur
l'établissement concerné (comme le ferait le middleware), puis les assertions
s'exécutent dans `self.session(...)`, où la RLS est réellement appliquée.
"""

import datetime
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import ProtectedError

from core.db.rls import current_tenant, temporary_tenant
from core.testing import RLSTestCase
from etablissements.models import Etablissement, Personnel
from patients.models import Assurance, Client, IndexRapprochement, PartageDossier, Patient, Telephone
from patients.services import (
    PartageDejaEffectue,
    PartageDossierError,
    partager_dossier,
    rechercher_correspondances,
)

CNI = "CNI-0042"


def creer_etablissement(nom, type_etablissement=Etablissement.TYPE_HOPITAL):
    return Etablissement.objects.create(
        nom_etablissement=nom, type_etablissement=type_etablissement, adresse="Bujumbura", telephone_contact="+25722000000"
    )


def creer_personnel(etablissement, identifiant):
    return Personnel.objects.create_user(
        identifiant_connexion=identifiant,
        email_professionnel=f"{identifiant}@example.org",
        password="x",
        nom="Nom",
        prenom="Prenom",
        role_metier="secretaire",
        date_embauche=datetime.date(2026, 1, 1),
        role_acces="standard",
        id_etablissement=etablissement,
    )


def creer_patient(etablissement, nom="Ndayishimiye", numero=CNI, **extra):
    RLSTestCase.positionner(etablissement.pk)
    return Patient.objects.create(
        nom_patient=nom,
        prenom_patient="Jean",
        date_naissance=datetime.date(1990, 5, 17),
        sexe="M",
        numero_piece_identite=numero,
        id_etablissement=etablissement,
        **extra,
    )


class BaseBloc2(RLSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hopital_a = creer_etablissement("Hôpital A")
        cls.hopital_b = creer_etablissement("Hôpital B")
        cls.pharmacie = creer_etablissement("Pharmacie P", Etablissement.TYPE_PHARMACIE)
        cls.agent_b = creer_personnel(cls.hopital_b, "agent_b")
        cls.agent_a = creer_personnel(cls.hopital_a, "agent_a")
        cls.patient_a = creer_patient(
            cls.hopital_a, numero=CNI, allergies="Pénicilline", antecedents_medicaux="Asthme"
        )
        cls.patient_b = creer_patient(cls.hopital_b, nom="Ndayishimiye (nouveau)", numero=CNI)


class IsolationRLSTests(BaseBloc2):
    def test_le_role_de_test_ne_contourne_pas_la_rls(self):
        with self.session(self.hopital_a), connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            self.assertFalse(cursor.fetchone()[0])

    def test_hopital_a_ne_voit_pas_un_patient_de_b(self):
        with self.session(self.hopital_a):
            self.assertEqual(Patient.objects.count(), 1)
            self.assertFalse(Patient.objects.filter(pk=self.patient_b.pk).exists())
        with self.session(self.hopital_b):
            self.assertFalse(Patient.objects.filter(pk=self.patient_a.pk).exists())

    def test_sans_contexte_aucune_ligne_visible(self):
        with self.session(None):
            self.assertEqual(Patient.objects.count(), 0)

    def test_hopital_a_ne_peut_ni_modifier_ni_supprimer_un_patient_de_b(self):
        with self.session(self.hopital_a):
            self.assertEqual(Patient.objects.filter(pk=self.patient_b.pk).update(nom_patient="X"), 0)
            self.assertEqual(Patient.objects.filter(pk=self.patient_b.pk)._raw_delete(using="default"), 0)

    def test_hopital_a_ne_peut_pas_inserer_une_ligne_au_nom_de_b(self):
        with self.session(self.hopital_a), self.assertRaises(DatabaseError), transaction.atomic():
            Patient.objects.bulk_create(
                [
                    Patient(
                        nom_patient="Intrus",
                        prenom_patient="X",
                        date_naissance=datetime.date(2000, 1, 1),
                        sexe="F",
                        id_etablissement=self.hopital_b,
                    )
                ]
            )


class IndexRapprochementRLSTests(BaseBloc2):
    def test_b_retrouve_l_entree_de_a_dans_l_index(self):
        with self.session(self.hopital_b):
            entrees = IndexRapprochement.objects.filter(numero_piece_identite=CNI)
            self.assertEqual({e.id_etablissement_id for e in entrees}, {self.hopital_a.pk, self.hopital_b.pk})

    def test_b_ne_peut_ni_modifier_ni_supprimer_l_entree_de_a(self):
        with self.session(self.hopital_b):
            entree_a = IndexRapprochement.objects.get(id_patient=self.patient_a.pk)
            self.assertEqual(
                IndexRapprochement.objects.filter(pk=entree_a.pk).update(numero_piece_identite="FALSIFIE"), 0
            )
            self.assertEqual(IndexRapprochement.objects.filter(pk=entree_a.pk)._raw_delete(using="default"), 0)
        with self.session(self.hopital_a):
            self.assertEqual(IndexRapprochement.objects.get(id_patient=self.patient_a.pk).numero_piece_identite, CNI)

    def test_b_ne_peut_pas_ecrire_une_entree_au_nom_de_a(self):
        with self.session(self.hopital_b), self.assertRaises(DatabaseError), transaction.atomic():
            IndexRapprochement.objects.create(
                numero_piece_identite="FAUX", id_patient=self.patient_b, id_etablissement=self.hopital_a
            )

    def test_l_index_est_alimente_a_la_creation_a_la_mise_a_jour_et_a_la_suppression_du_numero(self):
        self.positionner(self.hopital_a.pk)
        patient = Patient.objects.get(pk=self.patient_a.pk)
        patient.numero_piece_identite = "CNI-NOUVEAU"
        patient.save()
        self.assertEqual(IndexRapprochement.objects.get(id_patient=patient).numero_piece_identite, "CNI-NOUVEAU")
        patient.numero_piece_identite = None
        patient.save()
        self.assertFalse(IndexRapprochement.objects.filter(id_patient=patient).exists())


class PartageDossierTests(BaseBloc2):
    def partager(self, **kw):
        args = dict(id_patient_source=self.patient_a.pk, personnel=self.agent_b)
        args.update(kw)
        if "patient_destination" not in args:
            args["patient_destination"] = Patient.objects.get(pk=self.patient_b.pk)
        return partager_dossier(**args)

    def test_rapprochement_trouve_le_patient_de_l_autre_hopital(self):
        with self.session(self.hopital_b):
            trouvees = rechercher_correspondances(Patient.objects.get(pk=self.patient_b.pk))
        self.assertEqual([(e.id_patient_id, e.id_etablissement_id) for e in trouvees], [(self.patient_a.pk, self.hopital_a.pk)])

    def test_partage_copie_allergies_et_antecedents_et_trace_le_consentement(self):
        with self.session(self.hopital_b):
            partage = self.partager()
            self.assertEqual(current_tenant(), str(self.hopital_b.pk))  # contexte restauré
            nouveau = Patient.objects.get(pk=self.patient_b.pk)
            self.assertEqual((nouveau.allergies, nouveau.antecedents_medicaux), ("Pénicilline", "Asthme"))
            self.assertEqual(partage.matricule_personnel, self.agent_b)
            self.assertIsNotNone(partage.date_partage)
            self.assertEqual(partage.id_patient_source_id, self.patient_a.pk)
            # L'isolation reste totale en dehors de l'exception : A reste invisible pour B.
            self.assertFalse(Patient.objects.filter(pk=self.patient_a.pk).exists())

    def test_une_seule_fois(self):
        with self.session(self.hopital_b):
            self.partager()
            with self.assertRaises(PartageDejaEffectue):
                self.partager()

    def test_la_base_refuse_un_second_partage_vers_le_meme_destinataire(self):
        with self.session(self.hopital_b):
            self.partager()
            with self.assertRaises(IntegrityError), transaction.atomic():
                PartageDossier.objects.create(
                    id_patient_source=self.patient_a,
                    id_patient_destination_id=self.patient_b.pk,
                    matricule_personnel=self.agent_b,
                )

    def test_refuse_si_le_dossier_destinataire_a_deja_des_donnees_medicales(self):
        with self.session(self.hopital_b):
            destination = Patient.objects.get(pk=self.patient_b.pk)
            destination.allergies = "Arachides"
            destination.save()
            with self.assertRaises(PartageDossierError):
                self.partager(patient_destination=destination)
            self.assertEqual(Patient.objects.get(pk=self.patient_b.pk).allergies, "Arachides")

    def test_refuse_sans_correspondance_dans_l_index(self):
        autre = creer_patient(self.hopital_a, nom="Autre", numero="CNI-AUTRE")
        with self.session(self.hopital_b):
            with self.assertRaises(PartageDossierError):
                self.partager(id_patient_source=autre.pk)

    def test_refuse_un_patient_source_du_meme_hopital(self):
        double = creer_patient(self.hopital_b, nom="Doublon", numero=CNI)
        with self.session(self.hopital_b):
            with self.assertRaises(PartageDossierError):
                self.partager(id_patient_source=double.pk)

    def test_refuse_un_consentement_recueilli_par_le_personnel_d_un_autre_hopital(self):
        with self.session(self.hopital_b):
            with self.assertRaises(PartageDossierError):
                self.partager(personnel=self.agent_a)

    def test_refuse_si_la_session_n_est_pas_sur_l_hopital_destinataire(self):
        with self.session(self.hopital_a):
            with self.assertRaises(PartageDossierError):
                self.partager(patient_destination=self.patient_b)

    def test_un_patient_implique_dans_un_partage_ne_peut_pas_etre_supprime(self):
        with self.session(self.hopital_b):
            self.partager()
            with self.assertRaises(ProtectedError):
                Patient.objects.get(pk=self.patient_b.pk).delete()
        with self.session(self.hopital_a):
            with self.assertRaises(ProtectedError):
                Patient.objects.get(pk=self.patient_a.pk).delete()

    def test_temporary_tenant_restaure_le_contexte_meme_en_cas_d_erreur(self):
        with self.session(self.hopital_b):
            with self.assertRaises(ValueError):
                with transaction.atomic(), temporary_tenant(self.hopital_a.pk):
                    self.assertEqual(current_tenant(), str(self.hopital_a.pk))
                    raise ValueError
            self.assertEqual(current_tenant(), str(self.hopital_b.pk))

    def test_temporary_tenant_exige_une_transaction(self):
        with mock.patch.object(connection, "in_atomic_block", False):
            with self.assertRaises(RuntimeError):
                with temporary_tenant(self.hopital_a.pk):
                    pass


class ValidationEtContraintesTests(BaseBloc2):
    """Les règles tiennent aussi pour un enregistrement direct (API, shell), hors admin/formulaires."""

    def patient_sans_etablissement(self):
        return Patient(nom_patient="X", prenom_patient="Y", date_naissance=datetime.date(2000, 1, 1), sexe="M")

    def test_save_sans_etablissement_leve_validation_error_et_non_une_erreur_500(self):
        with self.assertRaises(ValidationError) as cm:
            self.patient_sans_etablissement().save()
        self.assertIn("id_etablissement", cm.exception.message_dict)

    def test_clean_sans_etablissement_ne_plante_pas(self):
        self.patient_sans_etablissement().clean()
        Client(nom="X").clean()
        Assurance(numero_police="P", nom_assureur="A", taux_prise_en_charge=50).clean()

    def test_un_patient_ne_peut_pas_etre_enregistre_dans_une_pharmacie_meme_via_save(self):
        self.positionner(self.pharmacie.pk)
        with self.assertRaises(ValidationError):
            Patient(
                nom_patient="X", prenom_patient="Y", date_naissance=datetime.date(2000, 1, 1),
                sexe="M", id_etablissement=self.pharmacie,
            ).save()

    def test_un_client_n_est_enregistrable_que_dans_une_pharmacie(self):
        self.positionner(self.hopital_a.pk)
        with self.assertRaises(ValidationError):
            Client(nom="X", id_etablissement=self.hopital_a).save()
        self.positionner(self.pharmacie.pk)
        Client(nom="X", id_etablissement=self.pharmacie).save()

    def test_taux_de_prise_en_charge_hors_0_100_refuse_par_save_et_par_la_base(self):
        self.positionner(self.hopital_a.pk)
        for taux in (-1, 100.01, 150):
            with self.assertRaises(ValidationError):
                Assurance(numero_police="P1", nom_assureur="A", taux_prise_en_charge=taux, id_etablissement=self.hopital_a).save()
        with self.assertRaises(IntegrityError), transaction.atomic():  # contournement de save()
            Assurance.objects.bulk_create(
                [Assurance(numero_police="P2", nom_assureur="A", taux_prise_en_charge=150, id_etablissement=self.hopital_a)]
            )
        Assurance(numero_police="P3", nom_assureur="A", taux_prise_en_charge=100, id_etablissement=self.hopital_a).save()

    def test_telephone_doit_etre_du_meme_etablissement_que_son_patient(self):
        self.positionner(self.hopital_a.pk)
        with self.assertRaises(ValidationError):
            Telephone(numero_telephone="79", type_telephone="mobile", id_patient=self.patient_a, id_etablissement=self.hopital_b).save()
        Telephone(numero_telephone="79", type_telephone="mobile", id_patient=self.patient_a, id_etablissement=self.hopital_a).save()

    def test_patient_et_index_sont_ecrits_ensemble_ou_pas_du_tout(self):
        self.positionner(self.hopital_a.pk)
        avant = Patient.objects.count()
        with mock.patch("patients.models.IndexRapprochement.objects") as faux_manager:
            faux_manager.update_or_create.side_effect = DatabaseError("panne simulée")
            with self.assertRaises(DatabaseError):
                Patient(
                    nom_patient="Atomique", prenom_patient="Test", date_naissance=datetime.date(2000, 1, 1),
                    sexe="M", numero_piece_identite="CNI-ATOM", id_etablissement=self.hopital_a,
                ).save()
        self.assertEqual(Patient.objects.count(), avant)
        self.assertFalse(Patient.objects.filter(nom_patient="Atomique").exists())

    def test_un_dossier_ne_peut_pas_etre_partage_avec_lui_meme(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PartageDossier.objects.create(
                id_patient_source=self.patient_a, id_patient_destination=self.patient_a, matricule_personnel=self.agent_a
            )
