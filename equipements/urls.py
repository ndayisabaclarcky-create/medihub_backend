from rest_framework.routers import DefaultRouter

from equipements.views import EquipementViewSet, InterventionViewSet

router = DefaultRouter()
router.register("equipements", EquipementViewSet, basename="equipement")
router.register("interventions", InterventionViewSet, basename="intervention-maintenance")
urlpatterns = router.urls
