"""Handlers: scan lifecycle → the external funnel (ADR 0016 D4/D5).

The producer side of ``soc.scan_completed`` (→ ``scan_digest``: ONE message per
completed scan with counts, never one per finding) and ``soc.scan_failed``
(→ ``scan_failed``: coverage is silently degraded until fixed). Subscribes to
the shared-kernel ``ScanCompleted`` / ``ScanFailed`` events the pillars emit
(cloud_posture's ingest, scanning's generic choreography) — the notifications
context couples to the kernel only, and delivery goes through the canonical
funnel like every other dispatch.
"""

from __future__ import annotations

from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import ScanCompleted, ScanFailed


@subscribes_to(ScanCompleted)
def handle_scan_completed(event: ScanCompleted) -> None:
    from components.notifications.infrastructure.adapters.soc_external_alerts import (
        dispatch_scan_completed,
    )

    dispatch_scan_completed(event)


@subscribes_to(ScanFailed)
def handle_scan_failed(event: ScanFailed) -> None:
    from components.notifications.infrastructure.adapters.soc_external_alerts import (
        dispatch_scan_failed,
    )

    dispatch_scan_failed(event)
