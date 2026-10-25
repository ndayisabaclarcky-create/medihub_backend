from rest_framework import serializers

from pharmacie.models import LignePrescription, LigneVente, LotMedicament, Medicament, Prescription, Vente


class MedicamentSerializer(serializers.ModelSerializer):
    quantite_stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = Medicament
        fields = (
            "id_medicament",
            "code_medicament",
            "nom_medicament",
            "dosage",
            "forme",
            "prix_catalogue",
            "seuil_alerte",
            "vente_libre",
            "quantite_stock",
        )
        read_only_fields = ("id_medicament", "quantite_stock")


class LotMedicamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LotMedicament
        fields = ("id_lot", "numero_lot", "date_peremption", "quantite_stock", "id_medicament")
        read_only_fields = ("id_lot",)


class LignePrescriptionSerializer(serializers.ModelSerializer):
    code_medicament = serializers.CharField(source="id_medicament.code_medicament", read_only=True)
    nom_medicament = serializers.CharField(source="id_medicament.nom_medicament", read_only=True)

    class Meta:
        model = LignePrescription
        fields = (
            "id_ligne_prescription",
            "id_medicament",
            "code_medicament",
            "nom_medicament",
            "posologie",
            "quantite_prescrite",
            "duree_traitement",
        )
        read_only_fields = (
            "id_ligne_prescription",
            "id_medicament",
            "code_medicament",
            "nom_medicament",
            "posologie",
            "quantite_prescrite",
            "duree_traitement",
        )


class PrescriptionSerializer(serializers.ModelSerializer):
    lignes = LignePrescriptionSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = (
            "id_prescription",
            "date_prescription",
            "matricule_personnel",
            "id_patient",
            "id_acte_consultation",
            "lignes",
        )
        read_only_fields = (
            "id_prescription",
            "date_prescription",
            "matricule_personnel",
            "id_patient",
            "id_acte_consultation",
            "lignes",
        )


class LignePrescriptionCreateSerializer(serializers.Serializer):
    id_medicament = serializers.UUIDField()
    posologie = serializers.CharField(max_length=50)
    quantite_prescrite = serializers.IntegerField(min_value=1)
    duree_traitement = serializers.IntegerField(min_value=1)


class PrescriptionCreateSerializer(serializers.Serializer):
    id_patient = serializers.UUIDField()
    id_consultation = serializers.UUIDField()
    date_prescription = serializers.DateField(required=False)
    lignes = LignePrescriptionCreateSerializer(many=True, allow_empty=False)


class LigneVenteSerializer(serializers.ModelSerializer):
    code_medicament = serializers.CharField(source="id_medicament.code_medicament", read_only=True)
    nom_medicament = serializers.CharField(source="id_medicament.nom_medicament", read_only=True)
    numero_lot = serializers.CharField(source="id_lot.numero_lot", read_only=True)

    class Meta:
        model = LigneVente
        fields = (
            "id_ligne_vente",
            "id_medicament",
            "code_medicament",
            "nom_medicament",
            "id_lot",
            "numero_lot",
            "quantite_demandee",
            "quantite_delivree",
            "prix_facture",
        )
        read_only_fields = fields


class VenteSerializer(serializers.ModelSerializer):
    id_patient = serializers.UUIDField(source="id_patient_id", read_only=True)
    id_client = serializers.UUIDField(source="id_client_id", read_only=True)
    id_prescription = serializers.UUIDField(source="id_prescription_id", read_only=True)
    matricule_personnel = serializers.UUIDField(source="matricule_personnel_id", read_only=True)
    lignes = LigneVenteSerializer(many=True, read_only=True)

    class Meta:
        model = Vente
        fields = (
            "id_vente",
            "date_vente",
            "id_patient",
            "id_client",
            "id_prescription",
            "nom_prescripteur_externe",
            "date_prescription_externe",
            "statut_paiement",
            "moyen_paiement",
            "matricule_personnel",
            "lignes",
        )
        read_only_fields = (
            "id_vente",
            "date_vente",
            "id_patient",
            "id_client",
            "id_prescription",
            "nom_prescripteur_externe",
            "date_prescription_externe",
            "statut_paiement",
            "moyen_paiement",
            "matricule_personnel",
            "lignes",
        )


class LigneVenteCreateSerializer(serializers.Serializer):
    id_medicament = serializers.UUIDField()
    quantite = serializers.IntegerField(min_value=1)


class ClientCreateSerializer(serializers.Serializer):
    nom = serializers.CharField(max_length=50)
    prenom = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    telephone_contact = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)


class VenteCreateSerializer(serializers.Serializer):
    lignes = LigneVenteCreateSerializer(many=True, allow_empty=False)
    client = ClientCreateSerializer(required=False)
    id_patient = serializers.UUIDField(required=False)
    id_prescription = serializers.UUIDField(required=False)
    nom_prescripteur_externe = serializers.CharField(max_length=80, required=False, allow_blank=True)
    date_prescription_externe = serializers.DateField(required=False, allow_null=True)
    statut_paiement = serializers.ChoiceField(
        choices=Vente.STATUT_PAIEMENT_CHOICES, required=False, allow_null=True
    )
    moyen_paiement = serializers.ChoiceField(
        choices=Vente.MOYEN_PAIEMENT_CHOICES, required=False, allow_null=True
    )
