from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import RolePermission, validation_api
from etablissements.models import Etablissement
from patients.models import Assurance, Client, Patient, PartageDossier, Telephone
from patients.serializers import (
    AssuranceSerializer,
    ClientSerializer,
    CorrespondanceSerializer,
    PatientSerializer,
    PartageDossierSerializer,
    TelephoneSerializer,
)
from patients.services import PartageDossierError, partager_dossier, rechercher_correspondances


class PartagerDossierCreateSerializer(serializers.Serializer):
    id_patient_source = serializers.UUIDField()
    consentement_recueilli = serializers.BooleanField()


class PersonnelMedicalOuAdmin(RolePermission):
    role_requis = ("administrateur", "medecin", "infirmier", "secretaire")


class PharmacienOuAdmin(RolePermission):
    role_requis = ("pharmacien", "administrateur")


class PersonnelSoignant(RolePermission):
    role_requis = ("administrateur", "medecin", "infirmier")


def _hopital_courant(request):
    if request.user.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Cette API est réservée aux hôpitaux.")


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    permission_classes = (IsAuthenticated, PharmacienOuAdmin)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "id_client"

    def get_queryset(self):
        if self.request.user.id_etablissement.type_etablissement != Etablissement.TYPE_PHARMACIE:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Les clients ne peuvent être consultés que dans une pharmacie.")
        return Client.objects.filter(id_etablissement_id=self.request.user.id_etablissement_id)

    def perform_create(self, serializer):
        if self.request.user.id_etablissement.type_etablissement != Etablissement.TYPE_PHARMACIE:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Les clients ne peuvent être gérés que dans une pharmacie.")
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class PatientViewSet(viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    permission_classes = (IsAuthenticated, PersonnelMedicalOuAdmin)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "id_patient"

    def get_permissions(self):
        if getattr(self, "action", None) == "correspondances":
            return [IsAuthenticated(), PersonnelSoignant()]
        return super().get_permissions()

    def get_queryset(self):
        _hopital_courant(self.request)
        return Patient.objects.select_related("id_assurance").prefetch_related("telephones").all()

    def perform_create(self, serializer):
        if self.request.user.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Les patients ne peuvent être gérés que dans un hôpital.")
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)

    @action(detail=True, methods=("get",), url_path="correspondances")
    def correspondances(self, request, id_patient=None):
        patient = self.get_object()
        if not patient.numero_piece_identite:
            return Response({"correspondances": []})
        matches = rechercher_correspondances(patient)
        return Response({"correspondances": CorrespondanceSerializer(matches, many=True).data})


class TelephoneViewSet(viewsets.ModelViewSet):
    serializer_class = TelephoneSerializer
    permission_classes = (IsAuthenticated, PersonnelMedicalOuAdmin)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "id_telephone"
    queryset = Telephone.objects.select_related("id_patient")

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset()

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class AssuranceViewSet(viewsets.ModelViewSet):
    serializer_class = AssuranceSerializer
    permission_classes = (IsAuthenticated, PersonnelMedicalOuAdmin)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "id_assurance"
    queryset = Assurance.objects.all()

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset()

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class PartageDossierViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PartageDossierSerializer
    permission_classes = (IsAuthenticated, PersonnelSoignant)
    lookup_field = "id_partage"

    def get_queryset(self):
        _hopital_courant(self.request)
        return PartageDossier.objects.filter(
            id_patient_destination__id_etablissement_id=self.request.user.id_etablissement_id
        )


class PartagerDossierAPIView(APIView):
    permission_classes = (IsAuthenticated, PersonnelSoignant)

    def post(self, request, id_patient):
        _hopital_courant(request)
        entree = PartagerDossierCreateSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        if not entree.validated_data["consentement_recueilli"]:
            raise serializers.ValidationError({"consentement_recueilli": "Le consentement oral doit avoir été recueilli."})
        try:
            patient_destination = Patient.objects.get(pk=id_patient)
            personnel = request.user
            partage = partager_dossier(
                patient_destination=patient_destination,
                id_patient_source=entree.validated_data["id_patient_source"],
                personnel=personnel,
            )
        except (DjangoValidationError, PartageDossierError) as exc:
            raise validation_api(exc) from exc
        except Patient.DoesNotExist as exc:
            raise serializers.ValidationError({"id_patient": "Patient destinataire introuvable."}) from exc
        return Response(PartageDossierSerializer(partage).data, status=status.HTTP_201_CREATED)
