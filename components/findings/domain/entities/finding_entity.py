"""FindingEntity — the normalized security finding as a domain object.

Lean and immutable (aggregate-light, per the architecture skill): invariants in
``__post_init__``, lifecycle transitions return new copies. Severity and status are
the shared value objects, so a Prowler finding and a Trivy finding are comparable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from components.shared_kernel.domain.security import FindingStatus, Severity


@dataclass(frozen=True)
class FindingEntity:
    id: UUID
    workspace_id: UUID
    source: str
    fingerprint: str
    asset_urn: str
    severity: Severity
    status: FindingStatus
    title: str
    first_seen_at: datetime
    last_seen_at: datetime
    description: str = ""
    remediation: str = ""
    compliance: dict = field(default_factory=dict)
    attributes: dict = field(default_factory=dict)
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("FindingEntity.source is required")
        if not self.fingerprint:
            raise ValueError("FindingEntity.fingerprint is required")
        if not self.asset_urn:
            raise ValueError("FindingEntity.asset_urn is required")
        if not self.title:
            raise ValueError("FindingEntity.title is required")

    @property
    def is_open(self) -> bool:
        return not self.status.is_terminal

    def observed(
        self,
        *,
        at: datetime,
        severity: Severity,
        title: str,
        description: str,
        remediation: str,
        compliance: dict,
        attributes: dict,
    ) -> FindingEntity:
        """Refresh this finding from a new observation of the same fingerprint.

        Bumps ``last_seen_at``, refreshes the mutable descriptive fields to the latest
        observed values, and **reopens** the finding if it had been resolved/suppressed
        (a re-observed misconfiguration is not fixed). ``first_seen_at`` is preserved.
        """
        reopened = self.status.is_terminal
        new_status = FindingStatus.OPEN if reopened else self.status
        return replace(
            self,
            last_seen_at=at,
            severity=severity,
            title=title,
            description=description,
            remediation=remediation,
            compliance=compliance,
            attributes=attributes,
            status=new_status,
            resolved_at=None if reopened else self.resolved_at,
        )

    def resolved(self, *, at: datetime) -> FindingEntity:
        """Mark the finding resolved (e.g. no longer observed / remediated)."""
        return replace(self, status=FindingStatus.RESOLVED, resolved_at=at)
