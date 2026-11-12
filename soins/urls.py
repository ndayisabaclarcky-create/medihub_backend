from rest_framework.routers import DefaultRouter

from soins.views import (
    ActeViewSet,
    ChambreViewSet,
    ConsultationViewSet,
    DisponibiliteMedecinViewSet,
    HospitalisationViewSet,
    LitViewSet,
    RendezVousViewSet,
)


router = DefaultRouter()
router.register("rendez-vous", RendezVousViewSet, basename="rendez-vous")
router.register("disponibilites", DisponibiliteMedecinViewSet, basename="disponibilite-medecin")
router.register("actes", ActeViewSet, basename="acte")
router.register("consultations", ConsultationViewSet, basename="consultation")
router.register("chambres", ChambreViewSet, basename="chambre")
router.register("lits", LitViewSet, basename="lit")
router.register("hospitalisations", HospitalisationViewSet, basename="hospitalisation")

urlpatterns = router.urls
