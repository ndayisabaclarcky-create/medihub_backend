from django.urls import path
from rest_framework.routers import DefaultRouter

from portail_patient.views import (
    DemanderCodeAPIView,
    DocumentPatientAPIView,
    DocumentsPatientAPIView,
    HopitauxPortailAPIView,
    MedecinsPortailAPIView,
    RendezVousPortailViewSet,
    SessionPortailAPIView,
    TelechargerDocumentPatientAPIView,
    VerifierCodeAPIView,
)


router = DefaultRouter()
router.register("rendez-vous", RendezVousPortailViewSet, basename="portail-rendez-vous")

urlpatterns = [
    path("hopitaux/", HopitauxPortailAPIView.as_view(), name="hopitaux-portail"),
    path("documents/", DocumentsPatientAPIView.as_view(), name="documents-patient"),
    path(
        "documents/<str:type_document>/<uuid:id_document>/",
        DocumentPatientAPIView.as_view(),
        name="document-patient",
    ),
    path(
        "documents/<str:type_document>/<uuid:id_document>/telecharger/",
        TelechargerDocumentPatientAPIView.as_view(),
        name="telecharger-document-patient",
    ),
    path("session/", SessionPortailAPIView.as_view(), name="session-portail-patient"),
    path("codes/demander/", DemanderCodeAPIView.as_view(), name="demander-code-portail"),
    path("codes/verifier/", VerifierCodeAPIView.as_view(), name="verifier-code-portail"),
    path("medecins/", MedecinsPortailAPIView.as_view(), name="medecins-portail"),
] + router.urls
