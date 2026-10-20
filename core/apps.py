from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Infrastructure commune (multi-tenant)"

    def ready(self):
        from core import checks  # noqa: F401  (enregistre les contrôles système)
