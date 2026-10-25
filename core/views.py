from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


def _session_payload(user):
    return {
        "matricule_personnel": str(user.pk),
        "identifiant_connexion": user.identifiant_connexion,
        "nom": user.nom,
        "prenom": user.prenom,
        "role_metier": user.role_metier,
        "role_acces": user.role_acces,
        "id_etablissement": str(user.id_etablissement_id),
        "type_etablissement": user.id_etablissement.type_etablissement,
    }


@method_decorator(csrf_protect, name="dispatch")
class SessionAPIView(APIView):
    """Connexion par session Django ; les requêtes d'écriture exigent le jeton CSRF."""

    permission_classes = (AllowAny,)

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"authenticated": False})
        return Response({"authenticated": True, "user": _session_payload(request.user)})

    def post(self, request):
        identifiant = request.data.get("identifiant_connexion")
        mot_de_passe = request.data.get("password")
        if not identifiant or not mot_de_passe:
            raise serializers.ValidationError({"detail": "Identifiant et mot de passe obligatoires."})
        user = authenticate(request, username=identifiant, password=mot_de_passe)
        if user is None:
            return Response({"detail": "Identifiant ou mot de passe invalide."}, status=status.HTTP_401_UNAUTHORIZED)
        login(request, user)
        return Response({"authenticated": True, "user": _session_payload(user)})

    def delete(self, request):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_204_NO_CONTENT)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
