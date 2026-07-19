from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = 'infrastructure.persistence.users'

    def ready(self):
        from components.identity.infrastructure.adapters.django_user_profile_signal_bridge import (
            DjangoUserProfileSignalBridge,
        )

        DjangoUserProfileSignalBridge.register()
