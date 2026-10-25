from datetime import date

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import RolePermission, validation_api
from etablissements.models import Etablissement, Medecin
from patients.models import Patient
from soins.models import Acte, Chambre, Consultation, Hospitalisation, Lit, RendezVous
from soins.serializers import (
    ActeSerializer,
    AffectationLitSerializer,
    ChambreSerializer,
    ConsultationCreateSerializer,
    ConsultationSerializer,
    HospitalisationCreateSerializer,
    HospitalisationSerializer,
    LitSerializer,
    RendezVousCreateSerializer,
    RendezVousSerializer,
)


class PersonnelMedical(RolePermission):
    role_requis = ("administrateur", "medecin", "infirmier", "secretaire")


class SoignantOuAdmin(RolePermission):
    role_requis = ("administrateur", "medecin", "infirmier")


class MedecinOuAdmin(RolePermission):
    role_requis = ("administrateur", "medecin")


class AdministrateurHopital(RolePermission):
    role_requis = ("administrateur",)


def _hopital_courant(request):
    if request.user.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
        raise PermissionDenied("Cette API est réservée aux hôpitaux.")


class RendezVousViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated, PersonnelMedical)
    serializer_class = RendezVousSerializer
    lookup_field = "id_rdv"
    queryset = RendezVous.objects.select_related("id_patient", "matricule_personnel")

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset()

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset().order_by("date_rendez_vous", "heure_rendez_vous"), many=True).data)

    def retrieve(self, request, id_rdv=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        _hopital_courant(request)
        entree = RendezVousCreateSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        medecin_id = entree.validated_data.get("matricule_personnel")
        if request.user.role_metier == "medecin":
            try:
                medecin_id = request.user.medecin.matricule_personnel_id
            except ObjectDoesNotExist as exc:
                raise PermissionDenied("Un compte médecin lié est requis.") from exc
            if entree.validated_data.get("matricule_personnel") and str(entree.validated_data["matricule_personnel"]) != str(medecin_id):
                raise PermissionDenied("Un médecin ne peut planifier que ses propres rendez-vous.")
        elif not medecin_id:
            raise serializers.ValidationError({"matricule_personnel": "Le médecin du rendez-vous est requis."})
        try:
            rendez_vous = RendezVous.objects.create(
                date_rendez_vous=entree.validated_data["date_rendez_vous"],
                heure_rendez_vous=entree.validated_data["heure_rendez_vous"],
                id_patient_id=entree.validated_data["id_patient"],
                matricule_personnel_id=medecin_id,
                id_etablissement_id=request.user.id_etablissement_id,
            )
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(self.get_serializer(rendez_vous).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",), url_path="annuler")
    def annuler(self, request, id_rdv=None):
        rendez_vous = self.get_object()
        if request.user.role_metier == "medecin" and str(rendez_vous.matricule_personnel_id) != str(request.user.pk):
            raise PermissionDenied("Un médecin ne peut annuler que ses propres rendez-vous.")
        try:
            rendez_vous.annuler()
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(self.get_serializer(rendez_vous).data)


class ActeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActeSerializer
    permission_classes = (IsAuthenticated, SoignantOuAdmin)
    queryset = Acte.objects.select_related("id_patient")
    lookup_field = "id_acte"

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset().order_by("-date_acte")


class ConsultationViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated, SoignantOuAdmin)
    serializer_class = ConsultationSerializer
    queryset = Consultation.objects.select_related("id_acte", "id_rendez_vous", "matricule_personnel", "matricule_interne")
    lookup_field = "id_acte"

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset().order_by("-id_acte__date_acte")

    def get_serializer_class(self):
        if self.action == "create":
            return ConsultationCreateSerializer
        return ConsultationSerializer

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, id_acte=None):
        return Response(self.get_serializer(self.get_object()).data)

    @transaction.atomic
    def create(self, request):
        _hopital_courant(request)
        if request.user.role_metier != "medecin":
            raise PermissionDenied("Seul un médecin peut rédiger une consultation.")
        entree = self.get_serializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            medecin = request.user.medecin
        except ObjectDoesNotExist as exc:
            raise PermissionDenied("Un compte médecin lié est requis pour signer une consultation.") from exc
        values = entree.validated_data
        try:
            acte = Acte.objects.create(
                date_acte=values["date_acte"],
                libelle_acte=values["libelle_acte"],
                montant_base=values["montant_base"],
                id_patient_id=values["id_patient"],
                id_etablissement_id=request.user.id_etablissement_id,
            )
            consultation = Consultation.objects.create(
                id_acte=acte,
                diagnostic=values["diagnostic"],
                observations=values.get("observations"),
                id_rendez_vous_id=values.get("id_rendez_vous"),
                matricule_personnel=medecin,
                matricule_interne_id=values.get("matricule_interne"),
                id_etablissement_id=request.user.id_etablissement_id,
            )
            if consultation.id_rendez_vous_id:
                rendez_vous = consultation.id_rendez_vous
                if rendez_vous.statut_rendez_vous == RendezVous.HONORE:
                    raise DjangoValidationError("Ce rendez-vous a déjà été traité.")
                if rendez_vous.statut_rendez_vous != RendezVous.PLANIFIE:
                    raise DjangoValidationError("Seul un rendez-vous planifié peut être marqué honoré.")
                rendez_vous.statut_rendez_vous = RendezVous.HONORE
                rendez_vous.save(update_fields=["statut_rendez_vous"])
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(ConsultationSerializer(consultation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",), url_path="clore")
    def clore(self, request, id_acte=None):
        consultation = self.get_object()
        if request.user.role_metier == "medecin" and str(consultation.matricule_personnel_id) != str(request.user.pk):
            raise PermissionDenied("Seul le médecin signataire peut clôturer cette consultation.")
        if consultation.statut_episode != Consultation.EN_COURS:
            raise serializers.ValidationError({"statut_episode": "Cette consultation est déjà clôturée."})
        consultation.statut_episode = Consultation.CLOS
        consultation.date_cloture_episode = timezone.now()
        try:
            consultation.save(update_fields=["statut_episode", "date_cloture_episode"])
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(ConsultationSerializer(consultation).data)


class ChambreViewSet(viewsets.ModelViewSet):
    serializer_class = ChambreSerializer
    permission_classes = (IsAuthenticated, AdministrateurHopital)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    queryset = Chambre.objects.select_related("code_service")
    lookup_field = "id_chambre"

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset()

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class LitViewSet(viewsets.ModelViewSet):
    serializer_class = LitSerializer
    permission_classes = (IsAuthenticated, AdministrateurHopital)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    queryset = Lit.objects.select_related("id_chambre")
    lookup_field = "id_lit"

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset()

    def perform_create(self, serializer):
        serializer.save(id_etablissement_id=self.request.user.id_etablissement_id)


class HospitalisationViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated, SoignantOuAdmin)
    serializer_class = HospitalisationSerializer
    queryset = Hospitalisation.objects.select_related("id_acte", "id_acte_consultation", "id_chambre", "id_lit")
    lookup_field = "id_acte"

    def get_queryset(self):
        _hopital_courant(self.request)
        return super().get_queryset().order_by("-date_entree")

    def get_serializer_class(self):
        if self.action == "create":
            return HospitalisationCreateSerializer
        return HospitalisationSerializer

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, id_acte=None):
        return Response(self.get_serializer(self.get_object()).data)

    @transaction.atomic
    def create(self, request):
        _hopital_courant(request)
        if request.user.role_metier not in ("medecin", "administrateur"):
            raise PermissionDenied("Seul un médecin peut décider une hospitalisation.")
        entree = self.get_serializer(data=request.data)
        entree.is_valid(raise_exception=True)
        values = entree.validated_data
        try:
            consultation = Consultation.objects.get(pk=values["id_acte_consultation"])
            acte = Acte.objects.create(
                date_acte=values["date_acte"],
                libelle_acte=values["libelle_acte"],
                montant_base=values["montant_base"],
                id_patient_id=consultation.id_acte.id_patient_id,
                id_etablissement_id=request.user.id_etablissement_id,
            )
            hospitalisation = Hospitalisation.objects.create(
                id_acte=acte,
                date_entree=values["date_entree"],
                id_acte_consultation=consultation,
                id_chambre_id=values.get("id_chambre"),
                id_lit_id=values.get("id_lit"),
                id_etablissement_id=request.user.id_etablissement_id,
            )
        except Consultation.DoesNotExist as exc:
            raise NotFound("Consultation introuvable dans cet hôpital.") from exc
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(HospitalisationSerializer(hospitalisation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",), url_path="affecter-lit")
    def affecter_lit(self, request, id_acte=None):
        if request.user.role_metier not in ("administrateur", "infirmier"):
            raise PermissionDenied("Seuls l'administration ou le personnel infirmier affectent les lits.")
        hospitalisation = self.get_object()
        if hospitalisation.date_sortie is not None:
            raise serializers.ValidationError({"date_sortie": "Une hospitalisation terminée ne peut plus être réaffectée."})
        entree = AffectationLitSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        hospitalisation.id_chambre_id = entree.validated_data["id_chambre"]
        hospitalisation.id_lit_id = entree.validated_data.get("id_lit")
        try:
            hospitalisation.save(update_fields=["id_chambre", "id_lit"])
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(HospitalisationSerializer(hospitalisation).data)

    @action(detail=True, methods=("post",), url_path="sortie")
    def sortie(self, request, id_acte=None):
        if request.user.role_metier not in ("administrateur", "medecin", "infirmier"):
            raise PermissionDenied("Seul le personnel soignant peut enregistrer une sortie.")
        hospitalisation = self.get_object()
        if hospitalisation.date_sortie is not None:
            raise serializers.ValidationError({"date_sortie": "La sortie de cette hospitalisation est déjà enregistrée."})
        date_sortie = request.data.get("date_sortie") or timezone.localdate()
        try:
            hospitalisation.date_sortie = date.fromisoformat(str(date_sortie))
        except ValueError as exc:
            raise serializers.ValidationError({"date_sortie": "Utilisez le format AAAA-MM-JJ."}) from exc
        try:
            hospitalisation.save(update_fields=["date_sortie"])
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        return Response(HospitalisationSerializer(hospitalisation).data)
