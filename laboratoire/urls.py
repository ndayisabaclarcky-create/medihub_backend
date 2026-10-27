from rest_framework.routers import DefaultRouter

from laboratoire.views import ExamenPrescritViewSet, ExamenViewSet, NotificationViewSet, PrescrireExamensAPIView


router = DefaultRouter()
router.register("examens", ExamenViewSet, basename="examen-laboratoire")
router.register("examens-prescrits", ExamenPrescritViewSet, basename="examen-prescrit")
router.register("notifications", NotificationViewSet, basename="notification-laboratoire")
router.register("prescrire", PrescrireExamensAPIView, basename="prescrire-examens")

urlpatterns = router.urls
