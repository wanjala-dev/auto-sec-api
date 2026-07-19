from __future__ import annotations

from django.db.models.signals import post_save

from infrastructure.persistence.workspaces.models import Workspace


class DjangoWorkspaceSignalBridge:
    def register(self, *, handler) -> None:
        post_save.connect(
            self._build_receiver(handler=handler),
            sender=Workspace,
            weak=False,
            dispatch_uid="workspace:post_save",
        )

    @staticmethod
    def _build_receiver(*, handler):
        def receiver(sender, instance, created, **kwargs):
            try:
                handler.execute(workspace=instance, created=created)
            except Exception:
                # Signals must not break the request lifecycle.
                pass

        return receiver
