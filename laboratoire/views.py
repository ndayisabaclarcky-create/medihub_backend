from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import RolePermission, validation_api
from etablissements.models import Etablissement
from laboratoire.models import Examen, ExamenPrescrit, Notification
from laboratoire.serializers import (
    ExamenPrescritSerializer,
    ExamenSerializer,
    NotificationSerializer,
    PrescrireExamensSerializer,
    ResultatCreateSerializer,
    ResultatExamenSerializer,
)
from laboratoire.services import LaboratoireError, enregistrer_resultat, prescrire_examens


class CatalogueLaboratoire(RolePermission):
    role_requis = ("administrateur", "medecin", "technicien_labo")


class PersonnelLaboratoire(RolePermission):
    role_requis = ("administrateur", "medecin", "technicien_labo")


class LaboratoireUniquement:
    def _verifier_hopital(self):
        if self.request.user.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise PermissionDenied("Les opérations de laboratoire sont réservées aux hôpitaux.")


class ExamenViewSet(LaboratoireUniquement, viewsets.ModelViewSet):
    serializer_class = ExamenSerializer
    permission_classes = (IsAuthenticated, CatalogueLaboratoire)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    lookup_field = "id_examen"
    queryset = Examen.objects.all()

    def get_queryset(self):
        self._verifier_hopital()
        return super().get_queryset().order_by("libelle_examen", "code_examen")

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update"):
            return [IsAuthenticated(), AdministrateurLaboratoire()]
        return super().get_permissions()

    def perform_create(self, serializer):
        self._verifier_hopital()
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class AdministrateurLaboratoire(RolePermission):
    role_requis = ("administrateur",)


class PrescrireExamensAPIView(LaboratoireUniquement, viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)

    def create(self, request):
        self._verifier_hopital()
        if request.user.role_metier != "medecin":
            raise PermissionDenied("Seul un médecin peut prescrire un examen (RG21).")
        entree = PrescrireExamensSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            medecin = request.user.medecin
        except ObjectDoesNotExist as exc:
            raise PermissionDenied("Un compte médecin lié est requis pour prescrire.") from exc
        try:
            examens, indisponibles = prescrire_examens(
                id_hopital=request.user.id_etablissement_id,
                matricule_medecin=medecin.matricule_personnel_id,
                id_consultation=entree.validated_data["id_acte_consultation"],
                codes_examens=entree.validated_data["codes_examens"],
            )
        except (DjangoValidationError, LaboratoireError) as exc:
            raise validation_api(exc) from exc
        return Response(
            {
                "examens_prescrits": ExamenPrescritSerializer(examens, many=True).data,
                "examens_non_disponibles": indisponibles,
                "message_non_disponibles": (
                    "Les examens absents du catalogue ne sont pas enregistrés; orientez le patient vers une structure externe."
                    if indisponibles
                    else None
                ),
            },
            status=status.HTTP_201_CREATED if examens else status.HTTP_200_OK,
        )


class ExamenPrescritViewSet(LaboratoireUniquement, viewsets.ReadOnlyModelViewSet):
    serializer_class = ExamenPrescritSerializer
    permission_classes = (IsAuthenticated, PersonnelLaboratoire)
    lookup_field = "id_acte"
    queryset = ExamenPrescrit.objects.select_related(
        "id_acte",
        "id_acte__id_patient",
        "id_acte_consultation",
        "id_examen",
        "matricule_medecin_prescripteur__matricule_personnel",
        "matricule_technicien",
        "resultat",
    )

    def get_queryset(self):
        self._verifier_hopital()
        qs = super().get_queryset()
        role = self.request.user.role_metier
        if role == "medecin":
            qs = qs.filter(matricule_medecin_prescripteur_id=self.request.user.pk)
        return qs.order_by("date_realisation", "-date_prescription_examen")

    def get_permissions(self):
        if self.action == "resultat":
            return [IsAuthenticated(), TechnicienLaboratoire()]
        return super().get_permissions()

    @action(detail=True, methods=("post",), url_path="resultat")
    def resultat(self, request, id_acte=None):
        self._verifier_hopital()
        examen_prescrit = self.get_object()
        entree = ResultatCreateSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            resultat = enregistrer_resultat(
                id_hopital=request.user.id_etablissement_id,
                id_acte_examen=examen_prescrit.pk,
                matricule_technicien=request.user.pk,
                contenu_resultat=entree.validated_data.get("contenu_resultat"),
            )
        except (DjangoValidationError, LaboratoireError) as exc:
            raise validation_api(exc) from exc
        return Response(ResultatExamenSerializer(resultat).data, status=status.HTTP_201_CREATED)


class TechnicienLaboratoire(RolePermission):
    role_requis = ("technicien_labo",)


class NotificationViewSet(LaboratoireUniquement, viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = (IsAuthenticated, PersonnelLaboratoire)
    lookup_field = "id_notification"
    queryset = Notification.objects.all()

    def get_queryset(self):
        self._verifier_hopital()
        return super().get_queryset().filter(
            matricule_personnel_destinataire_id=self.request.user.pk
        ).order_by("-date_creation")

    @action(detail=True, methods=("post",), url_path="lire")
    def lire(self, request, id_notification=None):
        notification = self.get_object()
        if not notification.lue:
            notification.lue = True
            from django.utils import timezone

            notification.date_lecture = timezone.now()
            try:
                notification.save(update_fields=("lue", "date_lecture"))
            except DjangoValidationError as exc:
                raise validation_api(exc) from exc
        return Response(self.get_serializer(notification).data)
