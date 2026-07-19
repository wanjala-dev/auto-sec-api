"""Composition root for the unified sign-off queue.

Wires the kernel ``SignOffQueueService`` to the process-wide registry + the
queue audit adapter. Keeping the concrete-adapter import here (not in the
controller) honours the rule that primary adapters depend on providers, never on
infrastructure directly.
"""

from __future__ import annotations

from components.sign_off.application.providers.sign_off_registry_provider import (
    get_sign_off_registry,
)
from components.sign_off.application.services.sign_off_queue_service import (
    SignOffQueueService,
)


class SignOffQueueProvider:
    def build_audit(self):
        from components.sign_off.infrastructure.adapters.kernel_sign_off_audit_adapter import (
            KernelSignOffAuditAdapter,
        )

        return KernelSignOffAuditAdapter()

    def build_event_publisher(self):
        # Lazy import (like build_audit) so the composition root doesn't drag
        # Celery into every import of this module.
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return CeleryEventPublisher()

    def build_service(self) -> SignOffQueueService:
        return SignOffQueueService(
            registry=get_sign_off_registry(),
            audit=self.build_audit(),
            event_publisher=self.build_event_publisher(),
        )


_default = SignOffQueueProvider()


def get_sign_off_queue_provider() -> SignOffQueueProvider:
    return _default
