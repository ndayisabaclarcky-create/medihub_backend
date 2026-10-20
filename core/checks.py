"""
Contrôle de démarrage : l'utilisateur PostgreSQL de Django ne doit ni être
super-utilisateur ni avoir l'attribut BYPASSRLS — sinon la RLS est ignorée
silencieusement et l'isolation multi-tenant ne protège plus rien.

Exécuté par `manage.py migrate` et `manage.py check --database default`.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.database)
def verifier_role_postgresql(app_configs, databases=None, **kwargs):
    from django.db import connections

    problemes = []
    for alias in databases or []:
        connexion = connections[alias]
        if connexion.vendor != "postgresql":
            continue
        with connexion.cursor() as cursor:
            cursor.execute(
                "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            ligne = cursor.fetchone()
        if ligne is None:
            continue
        utilisateur, est_super, bypass = ligne
        if est_super or bypass:
            motif = "super-utilisateur" if est_super else "BYPASSRLS"
            classe = Warning if settings.DEBUG else Error
            problemes.append(
                classe(
                    f"La base '{alias}' est utilisée avec le rôle PostgreSQL '{utilisateur}' ({motif}) : "
                    "la Row-Level Security est ignorée, aucun isolement entre hôpitaux.",
                    hint="Créez le rôle applicatif avec scripts/db_setup.sql puis mettez DB_USER=medihub_app dans .env.",
                    id="core.W001" if settings.DEBUG else "core.E001",
                )
            )
    return problemes
