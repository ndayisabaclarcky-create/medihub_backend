from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from core.api import RolePermission, validation_api
from equipements.models import Equipement, InterventionMaintenance
from equipements.serializers import EquipementSerializer, InterventionMaintenanceSerializer


class AdministrateurEtablissement(RolePermission):
    role_requis = ("administrateur",)


class EquipementViewSet(viewsets.ModelViewSet):
    serializer_class = EquipementSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "id_equipement"

    def get_queryset(self):
        return Equipement.objects.filter(id_etablissement_id=self.request.user.id_etablissement_id).select_related(
            "code_service"
        )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update"):
            return [IsAuthenticated(), AdministrateurEtablissement()]
        return super().get_permissions()

    def perform_create(self, serializer):
        try:
            serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc


class InterventionViewSet(viewsets.ModelViewSet):
    serializer_class = InterventionMaintenanceSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "id_intervention"

    def get_queryset(self):
        return InterventionMaintenance.objects.filter(
            id_etablissement_id=self.request.user.id_etablissement_id
        ).select_related("id_equipement", "matricule_technicien")

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update"):
            return [IsAuthenticated(), AdministrateurEtablissement()]
        return super().get_permissions()

    def perform_create(self, serializer):
        try:
            serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
