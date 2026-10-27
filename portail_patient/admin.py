from django.contrib import admin

from portail_patient.models import CodeVerification


@admin.register(CodeVerification)
class CodeVerificationAdmin(admin.ModelAdmin):
    list_display = ("id_code", "date_generation", "date_expiration", "utilise", "id_patient", "id_etablissement")
    list_filter = ("utilise", "id_etablissement")
    readonly_fields = tuple(
        field.name for field in CodeVerification._meta.fields if field.name != "code"
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
