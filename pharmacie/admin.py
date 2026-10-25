from django.contrib import admin

from pharmacie.models import (
    LignePrescription,
    LigneVente,
    LotMedicament,
    Medicament,
    Prescription,
    Vente,
)


@admin.register(Medicament)
class MedicamentAdmin(admin.ModelAdmin):
    list_display = (
        "code_medicament",
        "nom_medicament",
        "dosage",
        "forme",
        "prix_catalogue",
        "quantite_stock",
        "seuil_alerte",
        "vente_libre",
        "id_etablissement",
    )
    list_filter = ("vente_libre", "id_etablissement")
    search_fields = ("code_medicament", "nom_medicament")


@admin.register(LotMedicament)
class LotMedicamentAdmin(admin.ModelAdmin):
    list_display = ("numero_lot", "id_medicament", "date_peremption", "quantite_stock", "id_etablissement")
    list_filter = ("date_peremption", "id_etablissement")
    search_fields = ("numero_lot", "id_medicament__nom_medicament", "id_medicament__code_medicament")


class LignePrescriptionInline(admin.TabularInline):
    model = LignePrescription
    extra = 0
    can_delete = False
    readonly_fields = ("id_medicament", "posologie", "quantite_prescrite", "duree_traitement")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("date_prescription", "matricule_personnel", "id_patient", "id_acte_consultation", "id_etablissement")
    list_filter = ("date_prescription", "id_etablissement")
    inlines = (LignePrescriptionInline,)
    readonly_fields = (
        "date_prescription",
        "matricule_personnel",
        "id_patient",
        "id_acte_consultation",
        "id_etablissement",
    )

    def has_add_permission(self, request):
        # Les prescriptions doivent être créées en transaction via
        # pharmacie.services.rediger_prescription() avec au moins une ligne.
        return False


@admin.register(LignePrescription)
class LignePrescriptionAdmin(admin.ModelAdmin):
    list_display = ("id_prescription", "id_medicament", "posologie", "quantite_prescrite", "duree_traitement")
    list_filter = ("id_etablissement",)
    readonly_fields = (
        "id_prescription",
        "id_medicament",
        "posologie",
        "quantite_prescrite",
        "duree_traitement",
        "id_etablissement",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Vente)
class VenteAdmin(admin.ModelAdmin):
    list_display = ("id_vente", "date_vente", "id_etablissement", "matricule_personnel", "statut_paiement")
    list_filter = ("date_vente", "statut_paiement", "id_etablissement")
    readonly_fields = (
        "date_vente",
        "id_patient",
        "id_client",
        "id_prescription",
        "nom_prescripteur_externe",
        "date_prescription_externe",
        "statut_paiement",
        "moyen_paiement",
        "matricule_personnel",
        "id_etablissement",
    )

    def has_add_permission(self, request):
        # La vente et la décrémentation du stock sont atomiques dans le service.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LigneVente)
class LigneVenteAdmin(admin.ModelAdmin):
    list_display = (
        "id_vente",
        "id_medicament",
        "id_lot",
        "quantite_demandee",
        "quantite_delivree",
        "prix_facture",
        "id_etablissement",
    )
    list_filter = ("id_etablissement",)
    readonly_fields = (
        "id_vente",
        "id_medicament",
        "id_lot",
        "quantite_demandee",
        "quantite_delivree",
        "prix_facture",
        "id_etablissement",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
