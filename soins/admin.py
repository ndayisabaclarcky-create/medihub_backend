from django.contrib import admin

from soins.models import Acte, Chambre, Consultation, Hospitalisation, Lit, RendezVous


@admin.register(RendezVous)
class RendezVousAdmin(admin.ModelAdmin):
    list_display = (
        "date_rendez_vous",
        "heure_rendez_vous",
        "statut_rendez_vous",
        "id_patient",
        "matricule_personnel",
        "id_etablissement",
    )
    list_filter = ("statut_rendez_vous", "id_etablissement")


@admin.register(Acte)
class ActeAdmin(admin.ModelAdmin):
    list_display = ("libelle_acte", "date_acte", "montant_base", "id_patient", "id_etablissement")
    list_filter = ("id_etablissement",)
    search_fields = ("libelle_acte",)


@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display = ("id_acte", "diagnostic", "matricule_personnel", "statut_episode", "id_etablissement")
    list_filter = ("statut_episode", "id_etablissement")
    search_fields = ("diagnostic",)


@admin.register(Chambre)
class ChambreAdmin(admin.ModelAdmin):
    list_display = ("numero_chambre", "type_chambre", "code_service", "id_etablissement")
    list_filter = ("id_etablissement",)


@admin.register(Lit)
class LitAdmin(admin.ModelAdmin):
    list_display = ("numero_lit", "id_chambre", "id_etablissement")
    list_filter = ("id_etablissement",)


@admin.register(Hospitalisation)
class HospitalisationAdmin(admin.ModelAdmin):
    list_display = ("id_acte", "date_entree", "date_sortie", "id_chambre", "id_lit", "id_etablissement")
    list_filter = ("id_etablissement",)