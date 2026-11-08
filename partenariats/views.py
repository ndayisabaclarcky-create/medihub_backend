from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers

from core.api import validation_api
from etablissements.models import JournalAction
from partenariats.models import Partenariat
from partenariats.serializers import PartenariatCreateSerializer, PartenariatSerializer


class PartenariatViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = PartenariatSerializer
    lookup_field = "id_partenariat"

    def get_queryset(self):
        tenant = self.request.user.id_etablissement_id
        queryset = Partenariat.objects.filter(
            Q(id_etablissement_id=tenant) | Q(id_etablissement_partenaire_id=tenant)
        ).select_related("id_etablissement", "id_etablissement_partenaire")
        if self.action in ("repondre", "terminer"):
            queryset = queryset.select_for_update()
        return queryset

    def create(self, request):
        if request.user.role_metier != "administrateur":
            raise PermissionDenied("Seul un administrateur d'établissement peut proposer un partenariat.")
        entree = PartenariatCreateSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        donnees = dict(entree.validated_data)
        partenaire_id = donnees.pop("id_etablissement_partenaire")
        doublon = Partenariat.objects.filter(
            Q(id_etablissement_id=request.user.id_etablissement_id, id_etablissement_partenaire_id=partenaire_id)
            | Q(id_etablissement_id=partenaire_id, id_etablissement_partenaire_id=request.user.id_etablissement_id),
            type_partenariat=donnees["type_partenariat"],
            statut__in=(Partenariat.EN_ATTENTE, Partenariat.ACTIF),
        ).exists()
        if doublon:
            raise serializers.ValidationError(
                {"id_etablissement_partenaire": "Un partenariat de ce type est déjà en attente ou actif entre ces établissements."}
            )
        try:
            partenariat = Partenariat.objects.create(
                id_etablissement_id=request.user.id_etablissement_id,
                id_etablissement_partenaire_id=partenaire_id,
                matricule_proposant=request.user,
                **donnees,
            )
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        JournalAction.objects.create(
            type_action="partenariat_propose",
            details=f"Partenariat {partenariat.pk} proposé à {partenariat.id_etablissement_partenaire_id}",
            matricule_personnel=request.user,
            id_etablissement_id=request.user.id_etablissement_id,
        )
        return Response(self.get_serializer(partenariat).data, status=status.HTTP_201_CREATED)

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, id_partenariat=None):
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=("post",), url_path="repondre")
    @transaction.atomic
    def repondre(self, request, id_partenariat=None):
        if request.user.role_metier != "administrateur":
            raise PermissionDenied("Seul un administrateur peut répondre à un partenariat.")
        action_value = request.data.get("action")
        if action_value not in ("accepter", "refuser"):
            raise serializers.ValidationError({"action": "Choisissez accepter ou refuser."})
        partenariat = self.get_object()
        tenant = request.user.id_etablissement_id
        if partenariat.id_etablissement_partenaire_id != tenant:
            raise PermissionDenied("Seul l'établissement destinataire peut accepter ou refuser cette proposition.")
        if partenariat.statut != Partenariat.EN_ATTENTE:
            raise serializers.ValidationError({"statut": "Cette proposition a déjà reçu une réponse."})
        partenariat.statut = Partenariat.ACTIF if action_value == "accepter" else Partenariat.REFUSE
        partenariat.matricule_validateur = request.user
        partenariat.date_validation = timezone.now()
        try:
            partenariat.save(update_fields=("statut", "matricule_validateur", "date_validation"))
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        JournalAction.objects.create(
            type_action=f"partenariat_{action_value}",
            details=f"Partenariat {partenariat.pk} {action_value}",
            matricule_personnel=request.user,
            id_etablissement_id=tenant,
        )
        return Response(self.get_serializer(partenariat).data)

    @action(detail=True, methods=("post",), url_path="terminer")
    @transaction.atomic
    def terminer(self, request, id_partenariat=None):
        if request.user.role_metier != "administrateur":
            raise PermissionDenied("Seul un administrateur peut terminer un partenariat.")
        partenariat = self.get_object()
        tenant = request.user.id_etablissement_id
        if tenant not in (partenariat.id_etablissement_id, partenariat.id_etablissement_partenaire_id):
            raise PermissionDenied("Ce partenariat n'appartient pas à votre établissement.")
        if partenariat.statut != Partenariat.ACTIF:
            raise serializers.ValidationError({"statut": "Seul un partenariat actif peut être terminé."})
        partenariat.statut = Partenariat.TERMINE
        partenariat.save(update_fields=("statut",))
        JournalAction.objects.create(
            type_action="partenariat_termine",
            details=f"Partenariat {partenariat.pk} terminé",
            matricule_personnel=request.user,
            id_etablissement_id=tenant,
        )
        return Response(self.get_serializer(partenariat).data)
