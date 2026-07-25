"""Handler: persist a scanner's ``FindingObserved`` into the Finding SSOT.

The findings context owns this — a scanner emits ``FindingObserved`` (the shared-kernel
event) and this handler (behind the owner) records it (dedup + lifecycle) and emits
``FindingRaised``. Bound to the bus via ``@subscribes_to`` (the registry lives in the
shared kernel, so findings does not couple to any other context); the composition root
(``infrastructure/persistence/ai/apps.py``) lists this handler package for discovery.
"""

from __future__ import annotations

from components.findings.application.commands.record_observed_finding_command import (
    RecordObservedFindingCommand,
)
from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingObserved
from components.shared_kernel.domain.security import Severity


@subscribes_to(FindingObserved)
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
