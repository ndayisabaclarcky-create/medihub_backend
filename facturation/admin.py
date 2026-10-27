from django.contrib import admin

from facturation.models import Facture, LigneFacture, Paiement


class LigneFactureInline(admin.TabularInline):
    model = LigneFacture
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in LigneFacture._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display = (
        "id_facture", "date_emission", "id_patient", "id_acte_consultation", "statut_facture", "id_etablissement"
    )
    list_filter = ("statut_facture", "date_emission", "id_etablissement")
    search_fields = ("id_patient__nom_patient", "id_patient__prenom_patient")
    readonly_fields = tuple(field.name for field in Facture._meta.fields)
    inlines = (LigneFactureInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LigneFacture)
class LigneFactureAdmin(admin.ModelAdmin):
    list_display = ("designation", "quantite", "prix_unitaire", "montant_ligne", "id_facture")
    readonly_fields = tuple(field.name for field in LigneFacture._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ("id_paiement", "date_paiement", "montant_paye", "moyen_paiement", "id_facture")
    list_filter = ("date_paiement", "moyen_paiement", "id_etablissement")
    readonly_fields = tuple(field.name for field in Paiement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
