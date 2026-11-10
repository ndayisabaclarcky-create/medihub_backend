from datetime import datetime
from contextlib import contextmanager, nullcontext

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import validation_api
from core.db.rls import temporary_tenant
from etablissements.models import Etablissement
from patients.models import CodeComptePatient, ComptePatient, Patient, Telephone
from portail_patient.serializers import (
    ConnexionComptePatientSerializer,
    DemandeCodeSerializer,
    DisponibiliteSerializer,
    InscriptionComptePatientSerializer,
    PartagerHistoriqueSerializer,
    MedecinPortailSerializer,
    ProfilPatientSerializer,
    PrendreRendezVousSerializer,
    RendezVousNouveauHopitalSerializer,
    RendezVousPortailSerializer,
    VerificationComptePatientSerializer,
    VerifierCodeSerializer,
)
from portail_patient.documents import lister_documents, reponse_document
from portail_patient.partages import PartageHistoriqueError, partager_historique_patient
from portail_patient.services import (
    MESSAGE_CODE_INVALIDE,
    PortailPatientError,
    demander_code_connexion_patient,
    annuler_rendez_vous_portail,
    demander_code,
    inscrire_compte_patient,
    medecins_disponibles,
    patient_portail_connecte,
    prendre_rendez_vous,
    verifier_code,
    verifier_code_compte_patient,
)
from soins.models import RendezVous


class SessionPatientValide(BasePermission):
    def has_permission(self, request, view):
        return bool(
            not request.user.is_authenticated
            and request.session.get("portail_patient_id")
            and request.session.get("portail_hopital_id")
        )


class SessionComptePatientValide(BasePermission):
    def has_permission(self, request, view):
        return bool(request.session.get("portail_compte_patient_id"))


def _reponse_code_compte(challenge, code):
    resultat = {
        "detail": "Si les informations sont valides, un code a été envoyé au téléphone associé.",
        "id_code": str(challenge.pk),
        "expire_dans_secondes": 300,
    }
    if settings.PORTAIL_CODE_DEMO:
        resultat["code_simule"] = code
    return Response(resultat, status=status.HTTP_200_OK)


@method_decorator(csrf_protect, name="dispatch")
class InscriptionComptePatientAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        entree = InscriptionComptePatientSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            compte, challenge, code = inscrire_compte_patient(donnees=dict(entree.validated_data))
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        except IntegrityError as exc:
            raise serializers.ValidationError("L'identifiant ou le numéro de téléphone est déjà utilisé.") from exc
        return _reponse_code_compte(challenge, code)


@method_decorator(csrf_protect, name="dispatch")
class ConnexionComptePatientAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        entree = ConnexionComptePatientSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            compte, challenge, code = demander_code_connexion_patient(**entree.validated_data)
        except PortailPatientError as exc:
            raise serializers.ValidationError({"detail": "Identifiant ou mot de passe invalide."}) from exc
        return _reponse_code_compte(challenge, code)


@method_decorator(csrf_protect, name="dispatch")
class VerifierCodeComptePatientAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        entree = VerificationComptePatientSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                challenge = CodeComptePatient.objects.filter(pk=entree.validated_data["id_code"]).first()
                if challenge is None:
                    raise PortailPatientError(MESSAGE_CODE_INVALIDE)
                compte = verifier_code_compte_patient(
                    id_code=challenge.pk,
                    code=entree.validated_data["code"],
                    usage=challenge.usage,
                )
        except PortailPatientError as exc:
            raise serializers.ValidationError({"code": MESSAGE_CODE_INVALIDE}) from exc
        request.session.cycle_key()
        rotate_token(request)
        request.session.pop("portail_patient_id", None)
        request.session.pop("portail_hopital_id", None)
        request.session["portail_compte_patient_id"] = str(compte.pk)
        request.session.set_expiry(30 * 60)
        return Response({
            "authenticated": True,
            "compte_patient": {
                "id_compte_patient": str(compte.pk),
                "identifiant_connexion": compte.identifiant_connexion,
                "nom": compte.nom,
                "prenom": compte.prenom,
            },
            "expire_dans_secondes": 1800,
        })


@method_decorator(csrf_protect, name="dispatch")
class SessionPortailAPIView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        compte_id = request.session.get("portail_compte_patient_id")
        if compte_id:
            compte = ComptePatient.objects.filter(
                pk=compte_id, actif=True, telephone_verifie=True
            ).first()
            if compte is None:
                if request.user.is_authenticated:
                    request.session.pop("portail_compte_patient_id", None)
                    return Response({"authenticated": False, "mode": "personnel"})
                request.session.flush()
                return Response({"authenticated": False})
            return Response({
                "authenticated": True,
                "type_compte": "patient",
                "compte_patient": {
                    "id_compte_patient": str(compte.pk),
                    "identifiant_connexion": compte.identifiant_connexion,
                    "nom": compte.nom,
                    "prenom": compte.prenom,
                },
            })
        if request.user.is_authenticated:
            return Response({"authenticated": False, "mode": "personnel"})
        patient_id = request.session.get("portail_patient_id")
        id_hopital = request.session.get("portail_hopital_id")
        if not patient_id or not id_hopital:
            return Response({"authenticated": False})
        try:
            patient = patient_portail_connecte(session=request.session, id_hopital=id_hopital)
        except PortailPatientError:
            request.session.flush()
            return Response({"authenticated": False})
        return Response(
            {
                "authenticated": True,
                "patient": {
                    "id_patient": str(patient.pk),
                    "nom": patient.nom_patient,
                    "prenom": patient.prenom_patient,
                },
                "id_hopital": str(id_hopital),
            }
        )

    def delete(self, request):
        if request.session.get("portail_compte_patient_id"):
            request.session.pop("portail_compte_patient_id", None)
            if not request.user.is_authenticated:
                request.session.flush()
            return Response(status=status.HTTP_204_NO_CONTENT)
        if request.user.is_authenticated:
            raise serializers.ValidationError({"detail": "Cette action concerne uniquement la session du portail patient."})
        request.session.flush()
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class DemanderCodeAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        if request.user.is_authenticated:
            raise serializers.ValidationError(
                {"detail": "Déconnectez-vous du compte personnel avant de demander un code patient."}
            )
        entree = DemandeCodeSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            resultat = demander_code(**entree.validated_data)
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        reponse = {"detail": "Si ce dossier est connu, un code temporaire a été généré."}
        if resultat and settings.PORTAIL_CODE_DEMO:
            reponse["code_simule"] = resultat["code"]
            reponse["expire_dans_secondes"] = 300
        return Response(reponse, status=status.HTTP_200_OK)


class HopitauxPortailAPIView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        hopitaux = Etablissement.objects.filter(type_etablissement=Etablissement.TYPE_HOPITAL).order_by(
            "nom_etablissement"
        )
        return Response(
            [
                {
                    "id_etablissement": str(hopital.pk),
                    "nom_etablissement": hopital.nom_etablissement,
                    "adresse": hopital.adresse,
                }
                for hopital in hopitaux
            ]
        )


class DossiersComptePatientAPIView(APIView):
    permission_classes = (SessionComptePatientValide,)

    def get(self, request):
        compte = ComptePatient.objects.get(
            pk=request.session["portail_compte_patient_id"], actif=True, telephone_verifie=True
        )
        dossiers = []
        hopitaux = Etablissement.objects.filter(type_etablissement=Etablissement.TYPE_HOPITAL).order_by(
            "nom_etablissement"
        )
        with transaction.atomic():
            for hopital in hopitaux:
                with temporary_tenant(hopital.pk):
                    patient = Patient.objects.filter(
                        compte_patient=compte, id_etablissement_id=hopital.pk
                    ).only("id_patient", "nom_patient", "prenom_patient").first()
                    if patient:
                        dossiers.append({
                            "id_hopital": str(hopital.pk),
                            "nom_hopital": hopital.nom_etablissement,
                            "id_patient": str(patient.pk),
                            "nom": patient.nom_patient,
                            "prenom": patient.prenom_patient,
                        })
        return Response(dossiers)


@method_decorator(csrf_protect, name="dispatch")
class RendezVousNouveauHopitalAPIView(APIView):
    permission_classes = (SessionComptePatientValide,)

    def post(self, request, id_hopital):
        entree = RendezVousNouveauHopitalSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        compte = ComptePatient.objects.filter(
            pk=request.session["portail_compte_patient_id"], actif=True, telephone_verifie=True
        ).first()
        hopital = Etablissement.objects.filter(
            pk=id_hopital, type_etablissement=Etablissement.TYPE_HOPITAL
        ).first()
        if not compte or not hopital:
            raise serializers.ValidationError("Compte patient ou hôpital introuvable.")
        try:
            with transaction.atomic(), temporary_tenant(hopital.pk):
                patient = Patient.objects.filter(
                    compte_patient=compte, id_etablissement_id=hopital.pk
                ).first()
                dossier_cree = patient is None
                if patient is None:
                    patient = Patient.objects.create(
                        compte_patient=compte,
                        nom_patient=compte.nom,
                        prenom_patient=compte.prenom,
                        date_naissance=compte.date_naissance,
                        sexe=compte.sexe,
                        id_etablissement=hopital,
                    )
                    Telephone.objects.create(
                        numero_telephone=compte.numero_telephone,
                        type_telephone="mobile",
                        id_patient=patient,
                        id_etablissement=hopital,
                    )
                rendez_vous = prendre_rendez_vous(
                    patient=patient,
                    id_hopital=hopital.pk,
                    matricule_medecin=entree.validated_data["matricule_personnel"],
                    date_rendez_vous=entree.validated_data["date_rendez_vous"],
                    heure_rendez_vous=entree.validated_data["heure_rendez_vous"],
                )
                rendez_vous_data = RendezVousPortailSerializer(rendez_vous).data
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"heure_rendez_vous": "Ce créneau vient d'être réservé. Choisissez-en un autre."}
            ) from exc
        return Response({
            "id_patient": str(patient.pk),
            "dossier_cree": dossier_cree,
            "rendez_vous": rendez_vous_data,
        }, status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class PartagerHistoriquePatientAPIView(APIView):
    permission_classes = (SessionComptePatientValide,)

    def post(self, request):
        entree = PartagerHistoriqueSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        compte = ComptePatient.objects.filter(
            pk=request.session["portail_compte_patient_id"], actif=True, telephone_verifie=True
        ).first()
        if compte is None:
            raise serializers.ValidationError("La session du compte patient est invalide.")
        donnees = entree.validated_data
        try:
            historique = partager_historique_patient(
                compte=compte,
                id_hopital_source=donnees["id_hopital_source"],
                id_hopital_destination=donnees["id_hopital_destination"],
                documents=donnees.get("documents", []),
            )
        except PartageHistoriqueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response({
            "id_historique_partage": str(historique.pk),
            "date_consentement": historique.date_consentement,
            "id_hopital_destination": str(historique.id_etablissement_id),
            "nombre_documents": historique.documents.count(),
        }, status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class VerifierCodeAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        if request.user.is_authenticated:
            raise serializers.ValidationError(
                {"detail": "Déconnectez-vous du compte personnel avant d'ouvrir une session patient."}
            )
        entree = VerifierCodeSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            patient = verifier_code(**entree.validated_data)
        except PortailPatientError as exc:
            raise serializers.ValidationError({"code": MESSAGE_CODE_INVALIDE}) from exc
        request.session.cycle_key()
        rotate_token(request)
        request.session["portail_patient_id"] = str(patient.pk)
        request.session["portail_hopital_id"] = str(patient.id_etablissement_id)
        request.session.set_expiry(30 * 60)
        return Response(
            {
                "authenticated": True,
                "patient": {
                    "id_patient": str(patient.pk),
                    "nom": patient.nom_patient,
                    "prenom": patient.prenom_patient,
                },
                "expire_dans_secondes": 1800,
            }
        )


class MedecinsPortailAPIView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        if request.session.get("portail_compte_patient_id"):
            id_hopital = request.query_params.get("id_hopital")
            hopital = Etablissement.objects.filter(
                pk=id_hopital, type_etablissement=Etablissement.TYPE_HOPITAL
            ).first()
            if hopital is None or not ComptePatient.objects.filter(
                pk=request.session["portail_compte_patient_id"], actif=True, telephone_verifie=True
            ).exists():
                raise serializers.ValidationError({"id_hopital": "Choisissez un hôpital valide."})
            with transaction.atomic(), temporary_tenant(hopital.pk):
                medecins = medecins_disponibles(id_hopital=hopital.pk)
                return Response(MedecinPortailSerializer(medecins, many=True).data)
        try:
            patient = patient_portail_connecte(
                session=request.session,
                id_hopital=request.session["portail_hopital_id"],
            )
            medecins = medecins_disponibles(id_hopital=patient.id_etablissement_id)
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return Response(MedecinPortailSerializer(medecins, many=True).data)


class DisponibiliteNouveauHopitalAPIView(APIView):
    permission_classes = (SessionComptePatientValide,)

    def get(self, request):
        entree = DisponibiliteSerializer(data=request.query_params)
        entree.is_valid(raise_exception=True)
        id_hopital = request.query_params.get("id_hopital")
        hopital = Etablissement.objects.filter(
            pk=id_hopital, type_etablissement=Etablissement.TYPE_HOPITAL
        ).first()
        if hopital is None or not ComptePatient.objects.filter(
            pk=request.session["portail_compte_patient_id"], actif=True, telephone_verifie=True
        ).exists():
            raise serializers.ValidationError({"id_hopital": "Choisissez un hôpital valide."})
        valeurs = entree.validated_data
        with transaction.atomic(), temporary_tenant(hopital.pk):
            if not medecins_disponibles(id_hopital=hopital.pk).filter(
                pk=valeurs["matricule_personnel"]
            ).exists():
                raise serializers.ValidationError({"matricule_personnel": "Ce médecin n'exerce pas dans cet hôpital."})
            creneau = timezone.make_aware(
                datetime.combine(valeurs["date_rendez_vous"], valeurs["heure_rendez_vous"]),
                timezone.get_current_timezone(),
            )
            if creneau <= timezone.localtime(timezone.now()):
                return Response({"disponible": False, "raison": "date passée"})
            occupe = RendezVous.objects.filter(
                id_etablissement_id=hopital.pk,
                matricule_personnel_id=valeurs["matricule_personnel"],
                date_rendez_vous=valeurs["date_rendez_vous"],
                heure_rendez_vous=valeurs["heure_rendez_vous"],
            ).exclude(statut_rendez_vous=RendezVous.ANNULE).exists()
        return Response({"disponible": not occupe})


class ProfilPatientAPIView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        compte_id = request.session.get("portail_compte_patient_id")
        if compte_id:
            id_hopital = request.query_params.get("id_hopital")
            hopital = Etablissement.objects.filter(
                pk=id_hopital, type_etablissement=Etablissement.TYPE_HOPITAL
            ).first()
            compte = ComptePatient.objects.filter(
                pk=compte_id, actif=True, telephone_verifie=True
            ).first()
            if hopital is None or compte is None:
                raise serializers.ValidationError({"id_hopital": "Choisissez un hôpital valide."})
            with transaction.atomic(), temporary_tenant(hopital.pk):
                patient = Patient.objects.select_related(
                    "medecin_referent__matricule_personnel"
                ).prefetch_related("mesures_poids", "historiques_medicaux_recus__documents").filter(
                    compte_patient=compte, id_etablissement_id=hopital.pk
                ).first()
                if patient is None:
                    raise Http404
                return Response(ProfilPatientSerializer(patient).data)
        try:
            patient = patient_portail_connecte(
                session=request.session,
                id_hopital=request.session.get("portail_hopital_id"),
            )
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        patient = (
            Patient.objects.select_related("medecin_referent__matricule_personnel")
            .prefetch_related("mesures_poids")
            .get(pk=patient.pk)
        )
        return Response(ProfilPatientSerializer(patient).data)


class DocumentsPatientAPIView(APIView):
    permission_classes = (AllowAny,)

    @contextmanager
    def _patient(self, request):
        compte_id = request.session.get("portail_compte_patient_id")
        if compte_id:
            id_hopital = request.query_params.get("id_hopital")
            hopital = Etablissement.objects.filter(
                pk=id_hopital, type_etablissement=Etablissement.TYPE_HOPITAL
            ).first()
            compte = ComptePatient.objects.filter(
                pk=compte_id, actif=True, telephone_verifie=True
            ).first()
            if hopital is None or compte is None:
                raise serializers.ValidationError({"id_hopital": "Choisissez un hôpital valide."})
            with transaction.atomic(), temporary_tenant(hopital.pk):
                patient = Patient.objects.select_related("id_etablissement").filter(
                    compte_patient=compte, id_etablissement_id=hopital.pk
                ).first()
                if patient is None:
                    raise Http404
                yield patient
            return
        try:
            patient = patient_portail_connecte(
                session=request.session,
                id_hopital=request.session.get("portail_hopital_id"),
            )
            with nullcontext(patient):
                yield patient
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def get(self, request):
        with self._patient(request) as patient:
            return Response(lister_documents(patient))


class DocumentPatientAPIView(DocumentsPatientAPIView):
    def get(self, request, type_document, id_document):
        with self._patient(request) as patient:
            return reponse_document(patient=patient, type_document=type_document, id_document=id_document, telecharger=False)


class TelechargerDocumentPatientAPIView(DocumentsPatientAPIView):
    def get(self, request, type_document, id_document):
        with self._patient(request) as patient:
            return reponse_document(patient=patient, type_document=type_document, id_document=id_document, telecharger=True)


@method_decorator(csrf_protect, name="dispatch")
class RendezVousPortailViewSet(viewsets.GenericViewSet):
    permission_classes = (SessionPatientValide,)
    serializer_class = RendezVousPortailSerializer
    lookup_field = "id_rdv"

    def _patient(self, request):
        try:
            return patient_portail_connecte(
                session=request.session,
                id_hopital=request.session.get("portail_hopital_id"),
            )
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def get_queryset(self):
        patient = self._patient(self.request)
        return RendezVous.objects.filter(id_patient=patient).select_related(
            "matricule_personnel__matricule_personnel"
        ).order_by("-date_rendez_vous", "-heure_rendez_vous")

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, id_rdv=None):
        rendez_vous = self.get_object()
        return Response(self.get_serializer(rendez_vous).data)

    def create(self, request):
        patient = self._patient(request)
        entree = PrendreRendezVousSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        try:
            rendez_vous = prendre_rendez_vous(
                patient=patient,
                id_hopital=patient.id_etablissement_id,
                **entree.validated_data,
            )
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"heure_rendez_vous": "Ce créneau vient d'être réservé. Choisissez-en un autre."}
            ) from exc
        return Response(self.get_serializer(rendez_vous).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=("get",), url_path="disponibilite")
    def disponibilite(self, request):
        patient = self._patient(request)
        entree = DisponibiliteSerializer(data=request.query_params)
        entree.is_valid(raise_exception=True)
        valeurs = entree.validated_data
        if not medecins_disponibles(id_hopital=patient.id_etablissement_id).filter(
            pk=valeurs["matricule_personnel"]
        ).exists():
            raise serializers.ValidationError({"matricule_personnel": "Ce médecin n'exerce pas dans cet hôpital."})
        maintenant = timezone.localtime(timezone.now())
        creneau = timezone.make_aware(
            datetime.combine(valeurs["date_rendez_vous"], valeurs["heure_rendez_vous"]),
            timezone.get_current_timezone(),
        )
        if creneau <= maintenant:
            return Response({"disponible": False, "raison": "date passée"})
        occupe = RendezVous.objects.filter(
            matricule_personnel_id=valeurs["matricule_personnel"],
            date_rendez_vous=valeurs["date_rendez_vous"],
            heure_rendez_vous=valeurs["heure_rendez_vous"],
        ).exclude(statut_rendez_vous=RendezVous.ANNULE).exists()
        return Response({"disponible": not occupe})

    @action(detail=True, methods=("post",), url_path="annuler")
    def annuler(self, request, id_rdv=None):
        patient = self._patient(request)
        rendez_vous = self.get_object()
        try:
            annuler_rendez_vous_portail(rendez_vous=rendez_vous, patient=patient)
        except DjangoValidationError as exc:
            raise validation_api(exc) from exc
        except PortailPatientError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return Response(self.get_serializer(rendez_vous).data)
