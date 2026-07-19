from django.apps import AppConfig


class MembershipConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # Keep the legacy app label for migration compatibility while the module
    # now lives under the shared `apps.` namespace.
    name = "infrastructure.persistence.membership"
