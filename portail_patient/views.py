from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import validation_api
from etablissements.models import Etablissement
from portail_patient.serializers import (
    DemandeCodeSerializer,
    DisponibiliteSerializer,
    MedecinPortailSerializer,
    PrendreRendezVousSerializer,
    RendezVousPortailSerializer,
    VerifierCodeSerializer,
)
from portail_patient.services import (
    MESSAGE_CODE_INVALIDE,
    PortailPatientError,
    annuler_rendez_vous_portail,
    demander_code,
    medecins_disponibles,
    patient_portail_connecte,
    prendre_rendez_vous,
    verifier_code,
)
from soins.models import RendezVous


class SessionPatientValide(BasePermission):
    def has_permission(self, request, view):
        return bool(
            not request.user.is_authenticated
            and request.session.get("portail_patient_id")
            and request.session.get("portail_hopital_id")
        )


@method_decorator(csrf_protect, name="dispatch")
class SessionPortailAPIView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        if request.user.is_authenticated:
            return Response({"authenticated": False, "mode": "personnel"})
        patient_id = request.session.get("portail_patient_id")
        id_hopital = request.session.get("portail_hopital_id")
        if not patient_id or not id_hopital:
            return Response({"authenticated": False})
        try:
            patient = patient_portail_connecte(session=request.session, id_hopital=id_hopital)
        except PortailPatientError:
            request.session.flush()
            return Response({"authenticated": False})
        return Response(
            {
                "authenticated": True,
                "patient": {
                    "id_patient": str(patient.pk),
                    "nom": patient.nom_patient,
                    "prenom": patient.prenom_patient,
                },
                "id_hopital": str(id_hopital),
            }
        )

    def delete(self, request):
        if request.user.is_authenticated:
            raise serializers.ValidationError({"detail": "Cette action concerne uniquement la session du portail patient."})
        request.session.flush()
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class DemanderCodeAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        if request.user.is_authenticated:
            raise serializers.ValidationError(
                {"detail": "Déconnectez-vous du compte personnel avant de demander un code patient."}
            )
        entree = DemandeCodeSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            resultat = demander_code(**entree.validated_data)
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        reponse = {"detail": "Si ce dossier est connu, un code temporaire a été généré."}
        if resultat and settings.PORTAIL_CODE_DEMO:
            reponse["code_simule"] = resultat["code"]
            reponse["expire_dans_secondes"] = 300
        return Response(reponse, status=status.HTTP_200_OK)


class HopitauxPortailAPIView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        hopitaux = Etablissement.objects.filter(type_etablissement=Etablissement.TYPE_HOPITAL).order_by(
            "nom_etablissement"
        )
        return Response(
            [
                {
                    "id_etablissement": str(hopital.pk),
                    "nom_etablissement": hopital.nom_etablissement,
                    "adresse": hopital.adresse,
                }
                for hopital in hopitaux
            ]
        )


@method_decorator(csrf_protect, name="dispatch")
class VerifierCodeAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        if request.user.is_authenticated:
            raise serializers.ValidationError(
                {"detail": "Déconnectez-vous du compte personnel avant d'ouvrir une session patient."}
            )
        entree = VerifierCodeSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            patient = verifier_code(**entree.validated_data)
        except PortailPatientError as exc:
            raise serializers.ValidationError({"code": MESSAGE_CODE_INVALIDE}) from exc
        request.session.cycle_key()
        rotate_token(request)
        request.session["portail_patient_id"] = str(patient.pk)
        request.session["portail_hopital_id"] = str(patient.id_etablissement_id)
        request.session.set_expiry(30 * 60)
        return Response(
            {
                "authenticated": True,
                "patient": {
                    "id_patient": str(patient.pk),
                    "nom": patient.nom_patient,
                    "prenom": patient.prenom_patient,
                },
                "expire_dans_secondes": 1800,
            }
        )


class MedecinsPortailAPIView(APIView):
    permission_classes = (SessionPatientValide,)

    def get(self, request):
        try:
            patient = patient_portail_connecte(
                session=request.session,
                id_hopital=request.session["portail_hopital_id"],
            )
            medecins = medecins_disponibles(id_hopital=patient.id_etablissement_id)
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return Response(MedecinPortailSerializer(medecins, many=True).data)


@method_decorator(csrf_protect, name="dispatch")
class RendezVousPortailViewSet(viewsets.GenericViewSet):
    permission_classes = (SessionPatientValide,)
    serializer_class = RendezVousPortailSerializer
    lookup_field = "id_rdv"

    def _patient(self, request):
        try:
            return patient_portail_connecte(
                session=request.session,
                id_hopital=request.session.get("portail_hopital_id"),
            )
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def get_queryset(self):
        patient = self._patient(self.request)
        return RendezVous.objects.filter(id_patient=patient).select_related(
            "matricule_personnel__matricule_personnel"
        ).order_by("-date_rendez_vous", "-heure_rendez_vous")

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, id_rdv=None):
        rendez_vous = self.get_object()
        return Response(self.get_serializer(rendez_vous).data)

    def create(self, request):
        patient = self._patient(request)
        entree = PrendreRendezVousSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            rendez_vous = prendre_rendez_vous(
                patient=patient,
                id_hopital=patient.id_etablissement_id,
                **entree.validated_data,
            )
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"heure_rendez_vous": "Ce créneau vient d'être réservé. Choisissez-en un autre."}
            ) from exc
        return Response(self.get_serializer(rendez_vous).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=("get",), url_path="disponibilite")
    def disponibilite(self, request):
        patient = self._patient(request)
        entree = DisponibiliteSerializer(data=request.query_params)
        entree.is_valid(raise_exception=True)
        valeurs = entree.validated_data
        if not medecins_disponibles(id_hopital=patient.id_etablissement_id).filter(
            pk=valeurs["matricule_personnel"]
        ).exists():
            raise serializers.ValidationError({"matricule_personnel": "Ce médecin n'exerce pas dans cet hôpital."})
        maintenant = timezone.localtime(timezone.now())
        creneau = timezone.make_aware(
            datetime.combine(valeurs["date_rendez_vous"], valeurs["heure_rendez_vous"]),
            timezone.get_current_timezone(),
        )
        if creneau <= maintenant:
            return Response({"disponible": False, "raison": "date passée"})
        occupe = RendezVous.objects.filter(
            matricule_personnel_id=valeurs["matricule_personnel"],
            date_rendez_vous=valeurs["date_rendez_vous"],
            heure_rendez_vous=valeurs["heure_rendez_vous"],
        ).exclude(statut_rendez_vous=RendezVous.ANNULE).exists()
        return Response({"disponible": not occupe})

    @action(detail=True, methods=("post",), url_path="annuler")
    def annuler(self, request, id_rdv=None):
        patient = self._patient(request)
        rendez_vous = self.get_object()
        try:
            annuler_rendez_vous_portail(rendez_vous=rendez_vous, patient=patient)
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return Response(self.get_serializer(rendez_vous).data)
