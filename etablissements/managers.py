"""
Manager personnalisé pour PERSONNEL, qui sert directement de AUTH_USER_MODEL.
"""

from django.contrib.auth.base_user import BaseUserManager


class PersonnelManager(BaseUserManager):
    use_in_migrations = True

    def _create_personnel(self, identifiant_connexion, email_professionnel, password, **extra_fields):
        if not identifiant_connexion:
            raise ValueError("L'identifiant de connexion est obligatoire.")
        if not email_professionnel:
            raise ValueError("L'email professionnel est obligatoire.")
        email_professionnel = self.normalize_email(email_professionnel)
        personnel = self.model(
            identifiant_connexion=identifiant_connexion,
            email_professionnel=email_professionnel,
            **extra_fields,
        )
        personnel.set_password(password)
        personnel.save(using=self._db)
        return personnel

    def create_user(self, identifiant_connexion, email_professionnel, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_personnel(identifiant_connexion, email_professionnel, password, **extra_fields)

    def create_superuser(self, identifiant_connexion, email_professionnel, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role_metier", "administrateur")
        extra_fields.setdefault("role_acces", "admin_plateforme")
        extra_fields.setdefault("date_embauche", None)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superutilisateur doit avoir is_superuser=True.")
        if extra_fields.get("date_embauche") is None:
            from django.utils import timezone

            extra_fields["date_embauche"] = timezone.now().date()

        return self._create_personnel(identifiant_connexion, email_professionnel, password, **extra_fields)