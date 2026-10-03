from django.contrib import admin

from patients.models import (
    Assurance,
    Client,
    IndexRapprochement,
    Patient,
    PartageDossier,
    Telephone,
)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("nom", "prenom", "telephone_contact", "id_etablissement")
    list_filter = ("id_etablissement",)
    search_fields = ("nom", "prenom", "telephone_contact")


class TelephoneInline(admin.TabularInline):
    model = Telephone
    extra = 1
    fields = ("numero_telephone", "type_telephone", "id_etablissement")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("nom_patient", "prenom_patient", "date_naissance", "sexe", "id_etablissement", "id_assurance")
    list_filter = ("id_etablissement", "sexe")
    search_fields = ("nom_patient", "prenom_patient", "numero_piece_identite")
    inlines = [TelephoneInline]


@admin.register(Telephone)
class TelephoneAdmin(admin.ModelAdmin):
    list_display = ("numero_telephone", "type_telephone", "id_patient", "id_etablissement")
    list_filter = ("type_telephone", "id_etablissement")


@admin.register(Assurance)
class AssuranceAdmin(admin.ModelAdmin):
    list_display = ("nom_assureur", "numero_police", "taux_prise_en_charge", "id_etablissement")
    list_filter = ("id_etablissement",)
    search_fields = ("nom_assureur", "numero_police")


@admin.register(PartageDossier)
class PartageDossierAdmin(admin.ModelAdmin):
    list_display = ("id_patient_source", "id_patient_destination", "matricule_personnel", "date_partage")
    readonly_fields = ("date_partage",)


@admin.register(IndexRapprochement)
class IndexRapprochementAdmin(admin.ModelAdmin):
    list_display = ("numero_piece_identite", "id_patient", "id_etablissement")
    list_filter = ("id_etablissement",)
    search_fields = ("numero_piece_identite",)
