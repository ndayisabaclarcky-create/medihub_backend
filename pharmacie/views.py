from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db.models import Prefetch
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from pharmacie.models import LigneVente, LotMedicament, Medicament, Prescription, Vente
from pharmacie.serializers import (
    LotMedicamentSerializer,
    MedicamentSerializer,
    PrescriptionCreateSerializer,
    PrescriptionSerializer,
    VenteCreateSerializer,
    VenteSerializer,
)
from pharmacie.services import (
    PharmacieError,
    alertes_peremption,
    alertes_reapprovisionnement,
    consulter_prescription_hospitaliere,
    enregistrer_vente,
    rediger_prescription,
)


class RolePermission(BasePermission):
    role_requis = ()

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.role_metier in self.role_requis)
        )


class PharmacienOuAdmin(RolePermission):
    role_requis = ("pharmacien", "administrateur")


class PharmacienOnly(RolePermission):
    role_requis = ("pharmacien",)


class MedecinOnly(RolePermission):
    role_requis = ("medecin",)


def _message_validation(exc):
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            return exc.message_dict
        return exc.messages
    return str(exc)


class MedicamentViewSet(viewsets.ModelViewSet):
    serializer_class = MedicamentSerializer
    permission_classes = (IsAuthenticated, PharmacienOuAdmin)
    queryset = Medicament.objects.all().order_by("nom_medicament", "code_medicament")
    http_method_names = ("get", "post", "put", "patch", "head", "options")

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class LotMedicamentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = LotMedicamentSerializer
    permission_classes = (IsAuthenticated, PharmacienOuAdmin)
    queryset = LotMedicament.objects.select_related("id_medicament").all()
    http_method_names = ("get", "post", "head", "options")

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class PrescriptionListCreateView(APIView):
    permission_classes = (IsAuthenticated, MedecinOnly)

    def get(self, request):
        prescriptions = Prescription.objects.prefetch_related("lignes__id_medicament").order_by("-date_prescription")
        return Response(PrescriptionSerializer(prescriptions, many=True).data)

    def post(self, request):
        entree = PrescriptionCreateSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            medecin = request.user.medecin
        except ObjectDoesNotExist as exc:
            raise PermissionDenied("Un compte médecin lié est requis pour rédiger une prescription.") from exc
        try:
            prescription, _ = rediger_prescription(
                id_hopital=request.user.id_etablissement_id,
                matricule_medecin=medecin.matricule_personnel_id,
                id_patient=entree.validated_data["id_patient"],
                id_consultation=entree.validated_data["id_consultation"],
                date_prescription=entree.validated_data.get("date_prescription"),
                lignes=entree.validated_data["lignes"],
            )
        except (DjangoValidationError, PharmacieError) as exc:
            raise serializers.ValidationError(_message_validation(exc)) from exc
        return Response(PrescriptionSerializer(prescription).data, status=status.HTTP_201_CREATED)


class VenteListCreateView(APIView):
    permission_classes = (IsAuthenticated, PharmacienOnly)

    def get(self, request):
        lignes = LigneVente.objects.select_related("id_medicament", "id_lot")
        ventes = Vente.objects.prefetch_related(Prefetch("lignes", queryset=lignes)).order_by("-date_vente")
        return Response(VenteSerializer(ventes, many=True).data)

    def post(self, request):
        entree = VenteCreateSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            vente, delivrees = enregistrer_vente(
                id_pharmacie=request.user.id_etablissement_id,
                matricule_personnel=request.user.pk,
                **entree.validated_data,
            )
        except (DjangoValidationError, PharmacieError) as exc:
            raise serializers.ValidationError(_message_validation(exc)) from exc
        resultat = VenteSerializer(vente).data
        resultat["quantites_delivrees"] = delivrees
        return Response(resultat, status=status.HTTP_201_CREATED)


class PrescriptionHospitaliereDetailView(APIView):
    """Lecture étroite d'une ordonnance par une pharmacie de l'hôpital lié."""

    permission_classes = (IsAuthenticated, PharmacienOnly)

    def get(self, request, pk):
        try:
            prescription = consulter_prescription_hospitaliere(
                id_pharmacie=request.user.id_etablissement_id,
                id_prescription=pk,
            )
        except (DjangoValidationError, PharmacieError) as exc:
            raise serializers.ValidationError(_message_validation(exc)) from exc
        return Response(prescription)


class AlertesAPIView(APIView):
    permission_classes = (IsAuthenticated, PharmacienOuAdmin)

    def get(self, request):
        return Response(
            {
                "reapprovisionnement": MedicamentSerializer(alertes_reapprovisionnement(), many=True).data,
                "peremption": LotMedicamentSerializer(alertes_peremption(), many=True).data,
            }
        )
