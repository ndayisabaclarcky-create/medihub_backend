"""
Positionne, pour chaque requête, la variable de session PostgreSQL que lisent
les policies Row-Level Security (voir core/db/rls.py).

Doit être placé APRÈS django.contrib.auth.middleware.AuthenticationMiddleware
dans MIDDLEWARE (settings.py).

Ouvre lui-même sa propre transaction plutôt que de compter sur
ATOMIC_REQUESTS : ATOMIC_REQUESTS n'enveloppe que l'exécution de la vue, pas
les middlewares qui s'exécutent avant elle — un SET LOCAL positionné en dehors
de cette transaction expire avant même que la vue ne démarre.
"""

from django.db import connection, transaction


class EtablissementContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        id_etablissement = None
        if user is not None and getattr(user, "is_authenticated", False):
            id_etablissement = getattr(user, "id_etablissement_id", None)
        elif getattr(request, "session", None):
            # Après vérification OTP, le portail ne crée pas de compte Personnel :
            # la session donne uniquement le tenant du patient authentifié.
            if request.session.get("portail_patient_id"):
                id_etablissement = request.session.get("portail_hopital_id")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.current_etablissement', %s, true)",
                    [str(id_etablissement) if id_etablissement else ""],
                )
            response = self.get_response(request)

        return response
