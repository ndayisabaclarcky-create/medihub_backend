from django.core.checks import Error, Warning
from django.test import override_settings

from core.checks import verifier_role_postgresql
from core.testing import RLSTestCase, _role_courant_privilegie


class ControleRolePostgresqlTests(RLSTestCase):
    def test_aucun_probleme_avec_un_role_sans_privilege(self):
        with self.session(None):
            self.assertEqual(verifier_role_postgresql(None, databases=["default"]), [])

    def test_alerte_si_le_role_de_connexion_contourne_la_rls(self):
        if not _role_courant_privilegie():
            self.skipTest("Le rôle de connexion est déjà non privilégié (cas attendu en production).")
        with override_settings(DEBUG=True):
            [msg] = verifier_role_postgresql(None, databases=["default"])
            self.assertIsInstance(msg, Warning)
        with override_settings(DEBUG=False):
            [msg] = verifier_role_postgresql(None, databases=["default"])
            self.assertIsInstance(msg, Error)
