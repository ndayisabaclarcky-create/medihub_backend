from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import RolePermission, validation_api
from etablissements.models import Affectation, Etablissement, JournalAction, Medecin, Personnel, Service
from etablissements.serializers import (
    AffectationSerializer,
    EtablissementSerializer,
    EtablissementProvisionSerializer,
    MedecinSerializer,
    PersonnelSerializer,
    ServiceSerializer,
)


class AdministrateurEtablissement(RolePermission):
    role_requis = ("administrateur",)


class SuperUtilisateurPlateforme(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class ProvisionnerEtablissementAPIView(APIView):
    permission_classes = (IsAuthenticated, SuperUtilisateurPlateforme)

    def post(self, request):
        serializer = EtablissementProvisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            etablissement = serializer.save()
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(EtablissementSerializer(etablissement).data, status=status.HTTP_201_CREATED)


class EtablissementCourantViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EtablissementSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = "id_etablissement"

    def get_queryset(self):
        return Etablissement.objects.filter(pk=self.request.user.id_etablissement_id).select_related(
            "hopital", "pharmacie"
        )


class PersonnelViewSet(viewsets.ModelViewSet):
    serializer_class = PersonnelSerializer
    permission_classes = (IsAuthenticated, AdministrateurEtablissement)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "matricule_personnel"

    def get_queryset(self):
        return Personnel.objects.filter(id_etablissement_id=self.request.user.id_etablissement_id).order_by("nom", "prenom")


class MedecinViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MedecinSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = "matricule_personnel_id"

    def get_queryset(self):
        return Medecin.objects.filter(
            matricule_personnel__id_etablissement_id=self.request.user.id_etablissement_id
        ).select_related("matricule_personnel")


class ServiceViewSet(viewsets.ModelViewSet):
    serializer_class = ServiceSerializer
    permission_classes = (IsAuthenticated, AdministrateurEtablissement)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    queryset = Service.objects.select_related("matricule_chef_service")
    lookup_field = "code_service"

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class AffectationViewSet(viewsets.ModelViewSet):
    serializer_class = AffectationSerializer
    permission_classes = (IsAuthenticated, AdministrateurEtablissement)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    queryset = Affectation.objects.select_related("matricule_personnel", "code_service")
    lookup_field = "id_affectation"

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class JournalActionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = None
    permission_classes = (IsAuthenticated, AdministrateurEtablissement)
    queryset = JournalAction.objects.select_related("matricule_personnel")
    lookup_field = "id_journal"

    def get_serializer_class(self):
        from rest_framework import serializers

        class JournalSerializer(serializers.ModelSerializer):
            matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)

            class Meta:
                model = JournalAction
                fields = ("id_journal", "date_heure_action", "type_action", "details", "matricule_personnel")
                read_only_fields = fields

        return JournalSerializer
