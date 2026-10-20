"""
Outils de test pour la Row-Level Security.

Problème : si Django se connecte avec un super-utilisateur (ex. postgres), la
RLS est ignorée et un test d'isolation passerait « à vide ». `RLSTestCase.session()`
garantit donc que les requêtes s'exécutent avec un rôle SANS privilège :
  - si le rôle de connexion est déjà non privilégié (medihub_app) : rien à faire ;
  - sinon, bascule temporaire (SET LOCAL ROLE) vers un rôle jetable créé dans la
    transaction de test, et annulé avec elle.
"""

from contextlib import contextmanager

from unittest import skipUnless

from django.db import connection
from django.test import TestCase

from core.db.rls import SESSION_VAR

SONDE = "medihub_rls_sonde"


def _role_courant_privilegie():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        return cursor.fetchone()[0]


@skipUnless(connection.vendor == "postgresql", "La Row-Level Security n'existe que sous PostgreSQL.")
class RLSTestCase(TestCase):
    """TestCase dont `self.session(etablissement)` simule une requête d'un établissement."""

    @classmethod
    def setUpTestData(cls):
        cls._bascule_necessaire = _role_courant_privilegie()
        if cls._bascule_necessaire:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    DO $$ BEGIN
                        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{SONDE}') THEN
                            CREATE ROLE {SONDE} NOLOGIN NOSUPERUSER NOBYPASSRLS;
                        END IF;
                    END $$;
                    GRANT USAGE ON SCHEMA public TO {SONDE};
                    GRANT ALL ON ALL TABLES IN SCHEMA public TO {SONDE};
                    """
                )

    @staticmethod
    def positionner(id_etablissement):
        """Positionne la variable de session (sans changer de rôle) — pour créer des données de test."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config(%s, %s, true)", [SESSION_VAR, str(id_etablissement or "")])

    @contextmanager
    def session(self, etablissement):
        """Exécute le bloc comme une requête authentifiée de `etablissement`, RLS effective."""
        self.positionner(etablissement.pk if etablissement else "")
        if self._bascule_necessaire:
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL ROLE {SONDE}")
        try:
            yield
        finally:
            if self._bascule_necessaire:
                with connection.cursor() as cursor:
                    cursor.execute("RESET ROLE")
