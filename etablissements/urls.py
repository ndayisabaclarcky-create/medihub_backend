from django.urls import path
from rest_framework.routers import DefaultRouter

from etablissements.views import (
    AffectationViewSet,
    EtablissementCourantViewSet,
    JournalActionViewSet,
    MedecinViewSet,
    PersonnelViewSet,
    ProvisionnerEtablissementAPIView,
    ServiceViewSet,
)


router = DefaultRouter()
router.register("etablissement", EtablissementCourantViewSet, basename="etablissement-courant")
router.register("personnel", PersonnelViewSet, basename="personnel")
router.register("medecins", MedecinViewSet, basename="medecin")
router.register("services", ServiceViewSet, basename="service")
router.register("affectations", AffectationViewSet, basename="affectation")
router.register("journal", JournalActionViewSet, basename="journal-action")

urlpatterns = router.urls + [
    path("provisionner/", ProvisionnerEtablissementAPIView.as_view(), name="provisionner-etablissement"),
]
