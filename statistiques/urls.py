from django.urls import path

from statistiques.views import TableauDeBordAPIView

urlpatterns = [path("", TableauDeBordAPIView.as_view(), name="tableau-de-bord")]
