from django.apps import AppConfig


class SocialConfig(AppConfig):
    name = 'infrastructure.persistence.social'

    def ready(self):
        from components.social.infrastructure.adapters.django_workspace_membership_signal_bridge import (
            DjangoWorkspaceMembershipSignalBridge,
        )

        DjangoWorkspaceMembershipSignalBridge.register()
