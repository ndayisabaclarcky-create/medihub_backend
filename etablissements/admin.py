from django.contrib import admin

from etablissements.forms import PersonnelChangeForm, PersonnelCreationForm
from etablissements.models import (
    Affectation,
    Etablissement,
    Hopital,
    JournalAction,
    Medecin,
    Personnel,
    Pharmacie,
    Service,
)


@admin.register(Etablissement)
class EtablissementAdmin(admin.ModelAdmin):
    list_display = ("nom_etablissement", "type_etablissement", "telephone_contact", "date_creation_compte")
    list_filter = ("type_etablissement",)
    search_fields = ("nom_etablissement",)


@admin.register(Hopital)
class HopitalAdmin(admin.ModelAdmin):
    list_display = ("id_etablissement", "numero_agrement", "type_hopital")


@admin.register(Pharmacie)
class PharmacieAdmin(admin.ModelAdmin):
    list_display = ("id_etablissement", "numero_agrement_pharmaceutique", "id_etablissement_hopital_rattachement")


@admin.register(Personnel)
class PersonnelAdmin(admin.ModelAdmin):
    """
    ModelAdmin autonome plutôt qu'un héritage de django.contrib.auth.admin.UserAdmin :
    UserAdmin suppose un champ `username` codé en dur à plusieurs endroits (formulaires,
    ordering par défaut...), qui n'existe pas ici (USERNAME_FIELD = identifiant_connexion).
    Le motif get_form ci-dessous (form différent selon création/modification) est celui
    qu'utilise UserAdmin en interne — on le reproduit à la main pour rester sûr du résultat.
    """

    form = PersonnelChangeForm
    add_form = PersonnelCreationForm
    ordering = ("identifiant_connexion",)
    list_display = ("identifiant_connexion", "nom", "prenom", "role_metier", "id_etablissement", "actif", "is_staff")
    list_filter = ("role_metier", "id_etablissement", "actif", "is_staff")
    search_fields = ("identifiant_connexion", "nom", "prenom", "email_professionnel")
    filter_horizontal = ("groups", "user_permissions")
    fieldsets = (
        (None, {"fields": ("identifiant_connexion", "password")}),
        ("Informations personnelles", {"fields": ("nom", "prenom", "email_professionnel")}),
        ("Rôle et affectation", {"fields": ("role_metier", "role_acces", "id_etablissement", "date_embauche")}),
        ("Statut", {"fields": ("actif", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "identifiant_connexion",
                    "email_professionnel",
                    "nom",
                    "prenom",
                    "role_metier",
                    "role_acces",
                    "date_embauche",
                    "id_etablissement",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    def get_form(self, request, obj=None, **kwargs):
        defaults = {}
        if obj is None:
            defaults["form"] = self.add_form
        defaults.update(kwargs)
        return super().get_form(request, obj, **defaults)


@admin.register(Medecin)
class MedecinAdmin(admin.ModelAdmin):
    list_display = ("matricule_personnel", "specialite", "matricule_superviseur")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("nom_service", "id_etablissement", "matricule_chef_service")


@admin.register(Affectation)
class AffectationAdmin(admin.ModelAdmin):
    list_display = ("matricule_personnel", "code_service", "date_debut_affectation", "date_fin_affectation")


@admin.register(JournalAction)
class JournalActionAdmin(admin.ModelAdmin):
    list_display = ("type_action", "matricule_personnel", "id_etablissement", "date_heure_action")
    list_filter = ("type_action", "id_etablissement")
    readonly_fields = ("date_heure_action",)
