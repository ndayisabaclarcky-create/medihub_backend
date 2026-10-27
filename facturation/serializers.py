from decimal import Decimal

from rest_framework import serializers

from facturation.models import Facture, LigneFacture, Paiement


class LigneFactureSerializer(serializers.ModelSerializer):
    id_acte = serializers.UUIDField(source="id_acte_id", read_only=True, allow_null=True)
    id_ligne_vente = serializers.UUIDField(source="id_ligne_vente_id", read_only=True, allow_null=True)

    class Meta:
        model = LigneFacture
        fields = (
            "id_ligne_facture", "designation", "quantite", "prix_unitaire", "montant_ligne", "id_acte", "id_ligne_vente"
        )
        read_only_fields = fields


class PaiementSerializer(serializers.ModelSerializer):
    matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)

    class Meta:
        model = Paiement
        fields = ("id_paiement", "montant_paye", "date_paiement", "moyen_paiement", "matricule_personnel")
        read_only_fields = fields


class FactureSerializer(serializers.ModelSerializer):
    id_patient = serializers.UUIDField(source="id_patient_id", read_only=True)
    id_acte_consultation = serializers.UUIDField(source="id_acte_consultation_id", read_only=True)
    montant_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    taux_prise_en_charge = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    montant_assurance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    montant_patient = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_paye = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    solde_patient = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    lignes = LigneFactureSerializer(many=True, read_only=True)
    paiements = PaiementSerializer(many=True, read_only=True)

    class Meta:
        model = Facture
        fields = (
            "id_facture", "date_emission", "id_patient", "id_acte_consultation", "statut_facture",
            "montant_total", "taux_prise_en_charge", "montant_assurance", "montant_patient",
            "total_paye", "solde_patient", "lignes", "paiements",
        )
        read_only_fields = fields


class GenererFactureSerializer(serializers.Serializer):
    id_acte_consultation = serializers.UUIDField()


class PaiementCreateSerializer(serializers.Serializer):
    montant_paye = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    moyen_paiement = serializers.ChoiceField(choices=Paiement.MOYEN_CHOICES, required=False, allow_null=True)
