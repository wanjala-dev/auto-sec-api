"""The shared scan-execution choreography — DRY across every scanning pillar.

``run_scan_and_ingest`` is the ONE place a scan is executed and its findings land:

    create ScanRun(running) → scanner.scan(target) → record counts + emit one
    FindingObserved per finding (into the findings SSOT) + one ScanCompleted
    (the per-scan digest signal, ADR 0016 D5) → ScanRun(completed).

Every pillar (Prowler, Trivy, future arms) reuses this verbatim — a new pillar is a
``ScannerPort`` adapter + a registry entry, never a re-implementation of this dance
(ADR 0004: "a new pillar is a new adapter, not a new pipeline"). The scanning context
stays decoupled: it emits a shared-kernel event and never imports the ``findings``
context; pillar-specific detail rides in each ``NormalizedFinding.attributes``.
"""

from __future__ import annotations

import logging
from collections import Counter
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from components.shared_kernel.application.ports.scanner_port import (
    ProgressCallback,
    ScannerPort,
    ScanTarget,
)
from components.shared_kernel.domain.events import FindingObserved, ScanCompleted
from components.shared_kernel.domain.security import NormalizedFinding

logger = logging.getLogger(__name__)


def run_scan_and_ingest(
    *,
    workspace_id: UUID,
    source: str,
    target: ScanTarget,
    scanner: ScannerPort,
    connection_id: UUID | None = None,
    account_id: str = "",
    trigger: str = "manual",
    triggered_by: str | None = None,
    event_publisher=None,
    on_progress: ProgressCallback | None = None,
    on_completed=None,
):
    """Run *scanner* against *target*, record a ``ScanRun``, emit findings to the SSOT.

    The scan itself runs OUTSIDE any DB transaction (it is IO / a subprocess); only
    the finalize — updating the run + emitting ``FindingObserved`` after commit — is
    transactional, so a rolled-back finalize never emits orphan findings. A scan
    failure marks the run FAILED and re-raises so the caller (task) can react.
    Returns the ``ScanRun``.

    ``on_completed(run, result)`` (optional) fires after the run row is finalized —
    the pillar's post-ingest seam (persisting ``ScanResult.artifacts``, e.g. an image
    SBOM). POLICY: it is best-effort — a hook failure is logged and NEVER fails the
    completed scan (the findings + run record are already the truth).
    """
    from infrastructure.persistence.scanning.models import ScanRun

    now = timezone.now()
    run = ScanRun.objects.create(
        workspace_id=workspace_id,
        source=source,
        target_ref=target.identifier[:512],
        connection_id=connection_id,
        account_id=str(account_id or "")[:32],
        # Provenance (who caused this run) — rides every pillar's history row.
        trigger=(trigger or "manual")[:16],
        triggered_by_id=triggered_by or None,
        status=ScanRun.Status.RUNNING,
        started_at=now,
    )

    try:
        result = scanner.scan(target, on_progress=on_progress)
    except Exception as exc:
        logger.exception("scan_failed source=%s target=%s run_id=%s", source, target.identifier, run.id)
        ScanRun.objects.filter(id=run.id).update(
            status=ScanRun.Status.FAILED,
            error=str(exc)[:255],
            completed_at=timezone.now(),
        )
        raise

    observed = [_finding_observed(workspace_id, f, run_id=str(run.id)) for f in result.findings]

    # One ScanCompleted per run — the anti-flood digest signal (ADR 0016 D5): the
    # notifications context turns it into ONE external message per completed scan.
    severity_counts = Counter(f.severity.value for f in result.findings)
    completed_event = ScanCompleted(
        workspace_id=UUID(str(workspace_id)),
        source=source,
        engine=result.engine or source.rsplit(".", 1)[-1],
        scan_id=str(run.id),
        target_ref=target.identifier[:512],
        account_id=str(account_id or ""),
        total_checks=result.total_checks,
        findings_observed=len(observed),
        critical=severity_counts.get("critical", 0),
        high=severity_counts.get("high", 0),
        medium=severity_counts.get("medium", 0),
        low=severity_counts.get("low", 0),
    )

    with transaction.atomic():
        ScanRun.objects.filter(id=run.id).update(
            status=ScanRun.Status.COMPLETED,
            engine=result.engine,
            engine_version=result.engine_version,
            total_checks=result.total_checks,
            passed_count=result.passed_count,
            failed_count=result.failed_count,
            completed_at=timezone.now(),
        )
        _publish_after_commit([*observed, completed_event], event_publisher)

    logger.info(
        "scan_completed source=%s target=%s run_id=%s total=%s failed=%s emitted=%s",
        source,
        target.identifier,
        run.id,
        result.total_checks,
        result.failed_count,
        len(observed),
    )
    run.refresh_from_db()

    if on_completed is not None:
        try:
            on_completed(run, result)
        except Exception:
            # Best-effort by contract: the scan is already COMPLETED and its findings
            # emitted — a post-ingest failure (e.g. SBOM storage) must not undo that.
            logger.exception("scan_post_ingest_failed source=%s run_id=%s", source, run.id)

    return run


def _finding_observed(workspace_id: UUID, finding: NormalizedFinding, *, run_id: str = "") -> FindingObserved:
    """Map a ``NormalizedFinding`` (any engine) to a ``FindingObserved`` for the SSOT.

    ``run_id`` stamps the originating ``ScanRun`` first-class onto the event
    (audit R2): finding → run → trigger/user/engine-version becomes a plain
    lookup for every spine pillar.
    """
    return FindingObserved(
        workspace_id=workspace_id,
        source=finding.source,
        fingerprint=finding.fingerprint,
        asset_urn=finding.asset_urn,
        severity=finding.severity.value,
        title=finding.title,
        description=finding.description,
        remediation=finding.remediation,
        compliance=dict(finding.compliance),
        attributes=dict(finding.attributes),
        scan_run_id=run_id,
    )


def _publish_after_commit(events: list, event_publisher) -> None:
    """Emit the run's events (FindingObserved* + ScanCompleted) only after the run row commits."""
    if not events:
        return

    def _emit(publisher=event_publisher) -> None:
        if publisher is None:
            from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
                CeleryEventPublisher,
            )

            publisher = CeleryEventPublisher()
        for event in events:
            publisher.publish(event)

    transaction.on_commit(_emit)
