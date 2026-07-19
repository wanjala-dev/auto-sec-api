from django.apps import AppConfig


class RecycleBinConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'infrastructure.persistence.recycle_bin'
    label = 'recycle_bin'
    verbose_name = 'Recycle Bin'
