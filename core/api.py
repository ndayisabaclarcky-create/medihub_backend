"""Permissions et conversion d'erreurs communes aux API MediHub."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.permissions import BasePermission


class RolePermission(BasePermission):
    role_requis = ()

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.role_metier in self.role_requis)
        )


def validation_api(exc):
    """Transforme une ValidationError métier Django en réponse DRF 400."""
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            return serializers.ValidationError(exc.message_dict)
        return serializers.ValidationError(exc.messages)
    return serializers.ValidationError(str(exc))
