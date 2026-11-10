from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import RolePermission, validation_api
from etablissements.models import Etablissement
from facturation.models import Facture, Paiement
from facturation.serializers import FactureSerializer, GenererFactureSerializer, PaiementCreateSerializer, PaiementSerializer
from facturation.services import FacturationError, enregistrer_paiement, generer_facture
from soins.models import Consultation


class ComptableOuAdmin(RolePermission):
    role_requis = ("comptable", "administrateur")


class FactureViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FactureSerializer
    permission_classes = (IsAuthenticated, ComptableOuAdmin)
    lookup_field = "id_facture"
    queryset = Facture.objects.select_related("id_patient", "id_acte_consultation").prefetch_related(
        "lignes", "paiements"
    )

    def _verifier_hopital(self):
        if self.request.user.id_etablissement.type_etablissement != Etablissement.TYPE_HOPITAL:
            raise PermissionDenied("La facturation du bloc 6 est réservée aux hôpitaux.")

    def get_queryset(self):
        self._verifier_hopital()
        return super().get_queryset().order_by("-date_emission", "-id_facture")

    @action(detail=False, methods=("post",), url_path="generer")
    def generer(self, request):
        self._verifier_hopital()
        entree = GenererFactureSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            facture = generer_facture(
                id_hopital=request.user.id_etablissement_id,
                id_acte_consultation=entree.validated_data["id_acte_consultation"],
                matricule_personnel=request.user.pk,
            )
        except (DjangoValidationError, FacturationError) as exc:
            raise validation_api(exc) from exc
        return Response(self.get_serializer(facture).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=("get",), url_path="episodes-a-facturer")
    def episodes_a_facturer(self, request):
        """Expose au personnel de caisse le minimum requis pour émettre une facture."""
        self._verifier_hopital()
        episodes = (
            Consultation.objects.filter(
                id_etablissement_id=request.user.id_etablissement_id,
                statut_episode=Consultation.CLOS,
                facture__isnull=True,
            )
            .select_related("id_acte__id_patient")
            .order_by("-id_acte__date_acte")
        )
        return Response([
            {
                "id_acte": str(episode.pk),
                "id_patient": str(episode.id_acte.id_patient_id),
                "nom_patient": episode.id_acte.id_patient.nom_patient,
                "prenom_patient": episode.id_acte.id_patient.prenom_patient,
                "date_acte": episode.id_acte.date_acte,
                "libelle_acte": episode.id_acte.libelle_acte,
            }
            for episode in episodes
        ])

    @action(detail=True, methods=("get", "post"), url_path="paiements")
    def paiements(self, request, id_facture=None):
        self._verifier_hopital()
        facture = self.get_object()
        if request.method == "GET":
            paiements = Paiement.objects.filter(id_facture=facture).order_by("date_paiement", "id_paiement")
            return Response(PaiementSerializer(paiements, many=True).data)
        entree = PaiementCreateSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            paiement = enregistrer_paiement(
                id_hopital=request.user.id_etablissement_id,
                id_facture=facture.pk,
                matricule_personnel=request.user.pk,
                **entree.validated_data,
            )
        except (DjangoValidationError, FacturationError) as exc:
            raise validation_api(exc) from exc
        return Response(PaiementSerializer(paiement).data, status=status.HTTP_201_CREATED)
