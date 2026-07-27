from django.apps import AppConfig


class ResponseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.response"
    label = "response"
