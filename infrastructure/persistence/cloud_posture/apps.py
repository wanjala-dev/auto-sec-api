from django.apps import AppConfig


class CloudPostureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.cloud_posture"
    label = "cloud_posture"
