from django.urls import include, path
from rest_framework.routers import DefaultRouter

from pharmacie.views import (
    AlertesAPIView,
    LotMedicamentViewSet,
    MedicamentViewSet,
    PrescriptionHospitaliereDetailView,
    PrescriptionListCreateView,
    VenteListCreateView,
)


router = DefaultRouter()
router.register("medicaments", MedicamentViewSet, basename="medicament")
router.register("lots", LotMedicamentViewSet, basename="lot-medicament")

urlpatterns = [
    path("api/pharmacie/", include(router.urls)),
    path("api/pharmacie/prescriptions/", PrescriptionListCreateView.as_view(), name="prescriptions"),
    path(
        "api/pharmacie/prescriptions/<uuid:pk>/",
        PrescriptionHospitaliereDetailView.as_view(),
        name="prescription-hospitaliere-detail",
    ),
    path("api/pharmacie/ventes/", VenteListCreateView.as_view(), name="ventes"),
    path("api/pharmacie/alertes/", AlertesAPIView.as_view(), name="alertes-pharmacie"),
]
