from django.contrib import admin

from laboratoire.models import Examen, ExamenPrescrit, Notification, ResultatExamen


@admin.register(Examen)
class ExamenAdmin(admin.ModelAdmin):
    list_display = ("code_examen", "libelle_examen", "tarif", "id_etablissement")
    list_filter = ("id_etablissement",)
    search_fields = ("code_examen", "libelle_examen")


@admin.register(ExamenPrescrit)
class ExamenPrescritAdmin(admin.ModelAdmin):
    list_display = (
        "id_acte", "id_examen", "date_prescription_examen", "date_realisation",
        "matricule_medecin_prescripteur", "matricule_technicien", "id_etablissement",
    )
    list_filter = ("date_prescription_examen", "date_realisation", "id_etablissement")
    readonly_fields = tuple(field.name for field in ExamenPrescrit._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ResultatExamen)
class ResultatExamenAdmin(admin.ModelAdmin):
    list_display = ("id_resultat", "id_acte_examen_prescrit", "date_disponibilite", "id_etablissement")
    list_filter = ("date_disponibilite", "id_etablissement")
    readonly_fields = tuple(field.name for field in ResultatExamen._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "date_creation", "type_notification", "matricule_personnel_destinataire", "lue", "id_etablissement"
    )
    list_filter = ("type_notification", "lue", "id_etablissement")
    readonly_fields = tuple(field.name for field in Notification._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
