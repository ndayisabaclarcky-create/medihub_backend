from django.urls import path
from rest_framework.routers import DefaultRouter

from portail_patient.views import (
    DemanderCodeAPIView,
    HopitauxPortailAPIView,
    MedecinsPortailAPIView,
    RendezVousPortailViewSet,
    SessionPortailAPIView,
    VerifierCodeAPIView,
)


router = DefaultRouter()
router.register("rendez-vous", RendezVousPortailViewSet, basename="portail-rendez-vous")

urlpatterns = [
    path("hopitaux/", HopitauxPortailAPIView.as_view(), name="hopitaux-portail"),
    path("session/", SessionPortailAPIView.as_view(), name="session-portail-patient"),
    path("codes/demander/", DemanderCodeAPIView.as_view(), name="demander-code-portail"),
    path("codes/verifier/", VerifierCodeAPIView.as_view(), name="verifier-code-portail"),
    path("medecins/", MedecinsPortailAPIView.as_view(), name="medecins-portail"),
] + router.urls
