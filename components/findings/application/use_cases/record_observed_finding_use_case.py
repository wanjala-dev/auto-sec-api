"""Record a scanner observation into the Finding SSOT — dedup + lifecycle (ADR 0004).

The single write path the ``findings`` context owns. A scanner never writes a Finding
row; it emits ``FindingObserved`` and this use case (behind the owner) persists:

- first observation of a ``(workspace, source, fingerprint)`` → create OPEN, emit
  ``FindingRaised(is_new=True)``;
- re-observation, unchanged → bump ``last_seen_at`` only, emit nothing (steady-state
  noise suppression — a nightly re-scan must not re-alert on every still-open finding);
- re-observation with a higher/different severity, or of a resolved finding (reopen) →
  update + emit ``FindingRaised(is_new=False)``.

Framework-free: depends only on the ``FindingStorePort`` and an event publisher
(duck-typed ``publish``; optional so a mis-wired publisher can never break persistence).
"""

from __future__ import annotations

import logging
from uuid import uuid4

from components.findings.application.commands.record_observed_finding_command import (
    RecordObservedFindingCommand,
    RecordObservedFindingResult,
)
from components.findings.application.ports.finding_risk_store_port import FindingRiskStorePort
from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.domain.services.contextual_risk_scorer import extract_cve, score_finding
from components.shared_kernel.domain.events import FindingRaised
from components.shared_kernel.domain.security import FindingStatus

logger = logging.getLogger(__name__)


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class RecordObservedFindingUseCase:
    def __init__(
        self,
        *,
        store: FindingStorePort,
        event_publisher=None,
        risk_store: FindingRiskStorePort | None = None,
    ) -> None:
        self._store = store
        self._publisher = event_publisher
        self._risk_store = risk_store

    def execute(self, command: RecordObservedFindingCommand) -> RecordObservedFindingResult:
        existing = self._store.find_by_identity(command.workspace_id, command.source, command.fingerprint)

        if existing is None:
            finding = FindingEntity(
                id=uuid4(),
                workspace_id=command.workspace_id,
                source=command.source,
                fingerprint=command.fingerprint,
                asset_urn=command.asset_urn,
                severity=command.severity,
                status=FindingStatus.OPEN,
                title=command.title,
                first_seen_at=command.observed_at,
                last_seen_at=command.observed_at,
                description=command.description,
                remediation=command.remediation,
                compliance=dict(command.compliance or {}),
                attributes=dict(command.attributes or {}),
            )
            self._store.upsert(finding)
            self._stamp_provisional_risk(finding, at=command.observed_at)
            self._publish_raised(finding, is_new=True)
            logger.info(
                "finding_recorded_new workspace_id=%s source=%s finding_id=%s severity=%s",
                command.workspace_id,
                command.source,
                finding.id,
                finding.severity.value,
            )
            return RecordObservedFindingResult(finding_id=finding.id, is_new=True, changed=True)

        reopened = existing.status.is_terminal
        severity_changed = existing.severity != command.severity
        updated = existing.observed(
            at=command.observed_at,
            severity=command.severity,
            title=command.title,
            description=command.description,
            remediation=command.remediation,
            compliance=dict(command.compliance or {}),
            attributes=dict(command.attributes or {}),
        )
        self._store.upsert(updated)

        changed = reopened or severity_changed
        if changed:
            self._stamp_provisional_risk(updated, at=command.observed_at)
            self._publish_raised(updated, is_new=False)
            logger.info(
                "finding_recorded_changed workspace_id=%s finding_id=%s reopened=%s severity=%s",
                command.workspace_id,
                updated.id,
                reopened,
                updated.severity.value,
            )
        return RecordObservedFindingResult(finding_id=updated.id, is_new=False, changed=changed)

    def _stamp_provisional_risk(self, finding: FindingEntity, *, at) -> None:
        """Stamp a PROVISIONAL contextual-risk score synchronously at raise-time (ADR 0013 S1).

        Without this, a freshly-raised KEV/critical finding has no ``FindingRisk`` until the
        async ``rescore_finding`` runs, so it sorts to the BOTTOM (nulls_last) on the exact
        "what matters today" surface during that window — the opposite of its priority. The
        provisional score is the cheap severity-derived prior (+ the CVSS base already on the
        finding); it consults NO feeds and NO graph, so it is NOT a §6 heavy aggregation and
        is safe to compute inline. The async ``rescore_finding`` then refines it with
        EPSS/KEV/exposure. Best-effort: a mis-wired risk store must never fail the record.
        """
        if self._risk_store is None:
            return
        try:
            cve = extract_cve(finding.attributes)
            provisional = score_finding(
                severity=finding.severity,
                cvss_base=_as_float(finding.attributes.get("cvss_base")),
                has_cve=cve is not None,
                epss=None,
                epss_percentile=None,
                in_kev=False,
                exposure=None,
            )
            self._risk_store.upsert(
                workspace_id=finding.workspace_id,
                finding_id=finding.id,
                score=provisional,
                epss_score_date=None,  # provisional: no feed consulted yet
                kev_catalog_version=None,
                scored_at=at,
            )
        except Exception:
            logger.exception("finding_provisional_risk_stamp_failed finding_id=%s", finding.id)

    def _publish_raised(self, finding: FindingEntity, *, is_new: bool) -> None:
        if self._publisher is None:
            return
        self._publisher.publish(
            FindingRaised(
                workspace_id=finding.workspace_id,
                finding_id=finding.id,
                fingerprint=finding.fingerprint,
                asset_urn=finding.asset_urn,
                severity=finding.severity.value,
                status=finding.status.value,
                source=finding.source,
                title=finding.title,
                is_new=is_new,
            )
        )
