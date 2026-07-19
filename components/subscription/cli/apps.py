from django.apps import AppConfig


class SubscriptionCLIConfig(AppConfig):
    name = 'components.subscription.cli'
    label = 'subscription_cli'
    verbose_name = 'Subscription CLI'
    default_auto_field = 'django.db.models.BigAutoField'
