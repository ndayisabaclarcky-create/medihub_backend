"""
Formulaires d'admin dédiés pour PERSONNEL.
"""

from django import forms
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from etablissements.models import Personnel


class PersonnelCreationForm(forms.ModelForm):
    """Formulaire de création utilisé par l'admin : demande le mot de passe deux fois."""

    password1 = forms.CharField(label="Mot de passe", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmation du mot de passe", widget=forms.PasswordInput)

    class Meta:
        model = Personnel
        fields = (
            "identifiant_connexion",
            "email_professionnel",
            "nom",
            "prenom",
            "role_metier",
            "role_acces",
            "date_embauche",
            "id_etablissement",
        )

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Les deux mots de passe ne correspondent pas.")
        return password2

    def save(self, commit=True):
        personnel = super().save(commit=False)
        personnel.set_password(self.cleaned_data["password1"])
        if commit:
            personnel.save()
        return personnel


class PersonnelChangeForm(forms.ModelForm):
    """Formulaire de modification utilisé par l'admin : affiche le hash, jamais le mot de passe en clair."""

    password = ReadOnlyPasswordHashField(
        label="Mot de passe",
        help_text=(
            "Les mots de passe ne sont pas stockés en clair : impossible de l'afficher ici. "
            "Utilisez le lien de changement de mot de passe dédié de l'admin pour le modifier."
        ),
    )

    class Meta:
        model = Personnel
        fields = (
            "identifiant_connexion",
            "password",
            "email_professionnel",
            "nom",
            "prenom",
            "role_metier",
            "role_acces",
            "date_embauche",
            "id_etablissement",
            "actif",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )

    def clean_password(self):
        return self.initial.get("password")