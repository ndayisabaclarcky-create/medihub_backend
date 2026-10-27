from django.urls import path
from rest_framework.routers import DefaultRouter

from patients.views import (
    AssuranceViewSet,
    ClientViewSet,
    PartageDossierViewSet,
    PartagerDossierAPIView,
    PatientViewSet,
    TelephoneViewSet,
)


router = DefaultRouter()
router.register("clients", ClientViewSet, basename="client")
router.register("telephones", TelephoneViewSet, basename="telephone")
router.register("assurances", AssuranceViewSet, basename="assurance")
router.register("partages", PartageDossierViewSet, basename="partage-dossier")
router.register("", PatientViewSet, basename="patient")

urlpatterns = router.urls + [
    path("<uuid:id_patient>/partager/", PartagerDossierAPIView.as_view(), name="partager-dossier"),
]
