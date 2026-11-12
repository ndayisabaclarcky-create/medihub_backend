from django.urls import path
from rest_framework.routers import DefaultRouter

from portail_patient.views import (
    DemanderCodeAPIView,
    DossiersComptePatientAPIView,
    RendezVousComptePatientAPIView,
    CreneauxComptePatientAPIView,
    InscriptionComptePatientAPIView,
    ConnexionComptePatientAPIView,
    DisponibiliteNouveauHopitalAPIView,
    VerifierCodeComptePatientAPIView,
    RendezVousNouveauHopitalAPIView,
    PartagerHistoriquePatientAPIView,
    DocumentPatientAPIView,
    DocumentsPatientAPIView,
    HopitauxPortailAPIView,
    MedecinsPortailAPIView,
    ProfilPatientAPIView,
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
    path("compte/inscription/", InscriptionComptePatientAPIView.as_view(), name="inscription-compte-patient"),
    path("compte/connexion/", ConnexionComptePatientAPIView.as_view(), name="connexion-compte-patient"),
    path("compte/codes/verifier/", VerifierCodeComptePatientAPIView.as_view(), name="verifier-code-compte-patient"),
    path("compte/dossiers/", DossiersComptePatientAPIView.as_view(), name="dossiers-compte-patient"),
    path("compte/rendez-vous/", RendezVousComptePatientAPIView.as_view(), name="rendez-vous-compte-patient"),
    path("compte/creneaux/", CreneauxComptePatientAPIView.as_view(), name="creneaux-compte-patient"),
    path("compte/disponibilite/", DisponibiliteNouveauHopitalAPIView.as_view(), name="disponibilite-nouvel-hopital"),
    path("compte/rendez-vous/<uuid:id_hopital>/", RendezVousNouveauHopitalAPIView.as_view(), name="rendez-vous-nouvel-hopital"),
    path("compte/partages/historique/", PartagerHistoriquePatientAPIView.as_view(), name="partager-historique-patient"),
    path("codes/demander/", DemanderCodeAPIView.as_view(), name="demander-code-portail"),
    path("codes/verifier/", VerifierCodeAPIView.as_view(), name="verifier-code-portail"),
    path("medecins/", MedecinsPortailAPIView.as_view(), name="medecins-portail"),
    path("profil/", ProfilPatientAPIView.as_view(), name="profil-patient-portail"),
] + router.urls
