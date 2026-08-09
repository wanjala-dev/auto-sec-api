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
    # The ScanRun of the LAST observation (str(ScanRun.id), "" for run-less
    # sources). Updated on every re-observation, like ``last_seen_at`` — the
    # finding's provenance link to trigger/user/engine-version (audit R2).
    scan_run_id: str = ""
    resolved_at: datetime | None = None
    # Risk-acceptance context on the suppress action (ADR 0015 D9): the "why" +
    # optional time-box. resolve/reopen clear both; expiry ENFORCEMENT is P2.
    status_reason: str = ""
    suppress_expires_at: datetime | None = None
    # Read-only projection of the finding's live tags (ADR 0015). Never written
    # through the entity — the FindingTag join is mutated by TagFindingUseCase.
    tags: tuple[TagRef, ...] = ()

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
        scan_run_id: str = "",
    ) -> FindingEntity:
        """Refresh this finding from a new observation of the same fingerprint.

        Bumps ``last_seen_at``, refreshes the mutable descriptive fields to the latest
        observed values, and **reopens** the finding if it had been resolved/suppressed
        (a re-observed misconfiguration is not fixed). ``first_seen_at`` is preserved.
        ``scan_run_id`` tracks the last observing run; an empty value (a run-less
        source re-observing) keeps the previous link rather than erasing provenance.
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
            scan_run_id=scan_run_id or self.scan_run_id,
            status=new_status,
            resolved_at=None if reopened else self.resolved_at,
            status_reason="" if reopened else self.status_reason,
            suppress_expires_at=None if reopened else self.suppress_expires_at,
        )

    def resolved(self, *, at: datetime) -> FindingEntity:
        """Mark the finding resolved (e.g. no longer observed / remediated). Clears any
        suppress reason/expiry (ADR 0015 D9)."""
        return replace(
            self,
            status=FindingStatus.RESOLVED,
            resolved_at=at,
            status_reason="",
            suppress_expires_at=None,
        )

    def suppressed(self, *, at: datetime, reason: str = "", expires_at: datetime | None = None) -> FindingEntity:
        """Dismiss the finding as accepted-risk / false-positive (terminal, reversible).

        This is the finding-native "delete": the record is retained (auditable, and a
        re-observation reopens it), it simply drops off the open/actionable surfaces. The
        operator's soft-delete of a finding — never a hard row delete.

        ``reason`` + optional ``expires_at`` capture the risk-acceptance context
        (ADR 0015 D9 — the Snyk/DefectDojo semantics); expiry enforcement is P2."""
        return replace(
            self,
            status=FindingStatus.SUPPRESSED,
            resolved_at=at,
            status_reason=reason,
            suppress_expires_at=expires_at,
        )

    def reopened(self) -> FindingEntity:
        """Reopen a terminal (resolved/suppressed) finding — the undo for a mistaken
        resolve/dismiss. Clears ``resolved_at`` (and any suppress reason/expiry) and
        returns it to the actionable list."""
        return replace(
            self,
            status=FindingStatus.OPEN,
            resolved_at=None,
            status_reason="",
            suppress_expires_at=None,
        )
