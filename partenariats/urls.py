from rest_framework.routers import DefaultRouter

from partenariats.views import PartenariatViewSet

router = DefaultRouter()
router.register("", PartenariatViewSet, basename="partenariat")
urlpatterns = router.urls
