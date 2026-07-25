"""Handler: persist a scanner's ``FindingObserved`` into the Finding SSOT.

The findings context owns this — a scanner emits ``FindingObserved`` and this handler
(behind the owner) records it (dedup + lifecycle) and emits ``FindingRaised``.

Phase 3a defines it as a plain function, exercised directly by tests. It is NOT yet
bound to the event bus: the ``SubscriptionRegistry`` auto-discovery currently walks
only ``components.agents.application.handlers`` (see that module), and nothing emits
``FindingObserved`` until the cloud_posture producer lands. Phase 3b wires both — the
``@subscribes_to`` registration (once discovery is generalized) and the producer —
together, since binding a subscriber before there is a producer is dead wiring.
"""

from __future__ import annotations

from components.findings.application.commands.record_observed_finding_command import (
    RecordObservedFindingCommand,
)
from components.shared_kernel.domain.events import FindingObserved
from components.shared_kernel.domain.security import Severity


def handle_finding_observed(event: FindingObserved) -> None:
    from components.findings.application.providers.finding_provider import FindingProvider

    use_case = FindingProvider.build_record_observed_finding_use_case()
    use_case.execute(
        RecordObservedFindingCommand(
            workspace_id=event.workspace_id,
            source=event.source,
            fingerprint=event.fingerprint,
            asset_urn=event.asset_urn,
            severity=Severity.from_name(event.severity),
            title=event.title,
            observed_at=event.occurred_at,
            description=event.description,
            remediation=event.remediation,
            compliance=dict(event.compliance or {}),
            attributes=dict(event.attributes or {}),
        )
    )
