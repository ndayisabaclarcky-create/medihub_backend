from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from facturation.models import Facture, LigneFacture, Paiement
from laboratoire.models import ExamenPrescrit, ResultatExamen
from pharmacie.models import LigneVente, LotMedicament, Medicament, Vente
from soins.models import Consultation, Hospitalisation, RendezVous


class PeriodeSerializer(serializers.Serializer):
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)

    def validate(self, attrs):
        fin = attrs.get("date_fin", timezone.localdate())
        debut = attrs.get("date_debut", fin.replace(day=1))
        if debut > fin:
            raise serializers.ValidationError({"date_debut": "La date de début doit précéder la date de fin."})
        attrs["date_debut"], attrs["date_fin"] = debut, fin
        return attrs


class TableauDeBordAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    domaines_par_role = {
        "administrateur": {"soins", "pharmacie", "laboratoire", "facturation"},
        "medecin": {"soins", "laboratoire"},
        "infirmier": {"soins"},
        "secretaire": {"soins"},
        "pharmacien": {"pharmacie"},
        "technicien_labo": {"laboratoire"},
        "comptable": {"facturation"},
    }

    def get(self, request):
        entree = PeriodeSerializer(data=request.query_params)
        entree.is_valid(raise_exception=True)
        debut, fin = entree.validated_data["date_debut"], entree.validated_data["date_fin"]
        tenant = request.user.id_etablissement_id
        domaines = self.domaines_par_role.get(request.user.role_metier, set())
        resultat = {"date_debut": debut, "date_fin": fin}

        if "soins" in domaines:
            rdv = RendezVous.objects.filter(id_etablissement_id=tenant, date_rendez_vous__range=(debut, fin))
            resultat["soins"] = {
                "rendez_vous": rdv.count(),
                "rendez_vous_planifies": rdv.filter(statut_rendez_vous=RendezVous.PLANIFIE).count(),
                "rendez_vous_annules": rdv.filter(statut_rendez_vous=RendezVous.ANNULE).count(),
                "consultations": Consultation.objects.filter(
                    id_etablissement_id=tenant, id_acte__date_acte__range=(debut, fin)
                ).count(),
                "hospitalisations": Hospitalisation.objects.filter(
                    id_etablissement_id=tenant, date_entree__range=(debut, fin)
                ).count(),
                "hospitalisations_en_cours": Hospitalisation.objects.filter(
                    id_etablissement_id=tenant, date_sortie__isnull=True
                ).count(),
            }

        if "pharmacie" in domaines:
            aujourd_hui = timezone.localdate()
            limite = aujourd_hui + timedelta(days=90)
            stocks = Medicament.objects.filter(id_etablissement_id=tenant).annotate(
                stock_disponible=Coalesce(
                    Sum("lots__quantite_stock", filter=Q(lots__date_peremption__gte=aujourd_hui)),
                    0,
                )
            )
            stock_bas = stocks.filter(stock_disponible__lt=F("seuil_alerte")).count()
            lignes = LigneVente.objects.filter(
                id_etablissement_id=tenant,
                id_vente__date_vente__date__range=(debut, fin),
            )
            resultat["pharmacie"] = {
                "ventes": Vente.objects.filter(
                    id_etablissement_id=tenant, date_vente__date__range=(debut, fin)
                ).count(),
                "chiffre_ventes": lignes.aggregate(
                    total=Coalesce(Sum(F("prix_facture") * F("quantite_delivree")), Decimal("0.00"))
                )["total"],
                "medicaments_sous_seuil": stock_bas,
                "lots_proches_peremption": LotMedicament.objects.filter(
                    id_etablissement_id=tenant,
                    quantite_stock__gt=0,
                    date_peremption__gte=aujourd_hui,
                    date_peremption__lte=limite,
                ).count(),
            }

        if "laboratoire" in domaines:
            examens = ExamenPrescrit.objects.filter(
                id_etablissement_id=tenant, date_prescription_examen__range=(debut, fin)
            )
            resultat["laboratoire"] = {
                "examens_prescrits": examens.count(),
                "examens_realises": examens.filter(date_realisation__isnull=False).count(),
                "examens_en_attente": examens.filter(date_realisation__isnull=True).count(),
                "resultats_disponibles": ResultatExamen.objects.filter(
                    id_etablissement_id=tenant, date_disponibilite__range=(debut, fin)
                ).count(),
            }

        if "facturation" in domaines:
            factures = Facture.objects.filter(id_etablissement_id=tenant, date_emission__range=(debut, fin))
            resultat["facturation"] = {
                "factures_emises": factures.count(),
                "montant_facture": LigneFacture.objects.filter(
                    id_etablissement_id=tenant, id_facture__date_emission__range=(debut, fin)
                ).aggregate(total=Coalesce(Sum("montant_ligne"), Decimal("0.00")))["total"],
                "paiements_recus": Paiement.objects.filter(
                    id_etablissement_id=tenant, date_paiement__range=(debut, fin)
                ).aggregate(total=Coalesce(Sum("montant_paye"), Decimal("0.00")))["total"],
                "factures_soudees": factures.filter(statut_facture=Facture.SOLDEE).count(),
            }

        return Response(resultat)
