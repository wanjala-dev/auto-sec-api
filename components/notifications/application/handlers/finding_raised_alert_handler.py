"""Handler: a new critical finding → one individual external alert (ADR 0016 D5).

The producer side of the ``soc.finding_filed`` → ``finding_critical`` external
event. Subscribes to the shared-kernel ``FindingRaised`` (C1: the notifications
context couples to the kernel, never to the emitting ``findings`` context) and
dispatches through the canonical funnel — the ONLY sanctioned delivery path
(``tests/architecture/test_single_external_delivery_path.py``).

**The noise line.** Only a FIRST observation (``is_new=True``) of a CRITICAL
finding alerts individually; everything else is covered by the one-per-scan
digest (``soc.scan_completed``). A re-observation is steady-state noise and a
non-critical is digest material — a Prowler run raising 149 findings must post
the digest plus its criticals, never 149 messages (the regression ADR 0016
retired).

KEV note (ADR 0016 D5): the leg's severity-floor bypass reads
``metadata["in_kev"]``, but ``FindingRaised`` does not carry a KEV flag yet —
severity is the only gate available at this producer. When the event grows KEV
context, widen the gate here and stamp ``in_kev`` into the metadata.
"""

from __future__ import annotations

from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingRaised
from components.shared_kernel.domain.security import Severity


@subscribes_to(FindingRaised)
def handle_finding_raised_alert(event: FindingRaised) -> None:
    if not event.is_new:
        return  # re-observation of an already-open finding — steady-state noise
    if (event.severity or "").strip().lower() != Severity.CRITICAL.value:
        return  # non-critical → the per-scan digest covers it

    from components.notifications.infrastructure.adapters.soc_external_alerts import (
        dispatch_finding_filed,
    )

    dispatch_finding_filed(event)
