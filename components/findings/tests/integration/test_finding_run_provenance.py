"""Run provenance reaches the Finding SSOT (scanner-architecture audit R2).

Before this thread existed, ``FindingObserved`` dropped the run id at the event
boundary: even where ``ScanRun`` knew trigger/triggered_by/engine-version, no
finding could ever answer "which run found this, who triggered it". These tests
lock the whole chain: the spine choreography stamps ``scan_run_id`` on the
event, the findings handler persists it, and a re-observation moves it to the
newest run without a run-less source erasing it.
"""

from __future__ import annotations

import pytest

from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
from components.shared_kernel.application.ports.scanner_port import ScanResult, ScanTarget
from components.shared_kernel.domain.events import FindingObserved
from components.shared_kernel.domain.security import NormalizedFinding, Severity
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "container_security.trivy"


class _StubScanner:
    def __init__(self, result):
        self._result = result

    def scan(self, target, on_progress=None):
        return self._result


def _finding(suffix: str) -> NormalizedFinding:
    return NormalizedFinding(
        source=_SOURCE,
        fingerprint=f"fp-{suffix}",
        asset_urn=f"urn:image/repo:tag/{suffix}",
        severity=Severity.HIGH,
        title=f"CVE-2026-000{suffix} in openssl",
    )


def _result(findings):
    return ScanResult(
        findings=tuple(findings),
        engine="trivy",
        engine_version="0.58.0",
        total_checks=len(findings),
        passed_count=0,
        failed_count=len(findings),
    )


def _run(ws, findings):
    return run_scan_and_ingest(
        workspace_id=ws.id,
        source=_SOURCE,
        target=ScanTarget(identifier="repo/image:tag"),
        scanner=_StubScanner(_result(findings)),
        # No event_publisher → the real bus; eager Celery runs the bound
        # findings handler synchronously when the on_commit callbacks fire.
    )


def test_spine_run_id_lands_on_the_persisted_finding(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    with django_capture_on_commit_callbacks(execute=True):
        run = _run(ws, [_finding("1")])

    finding = Finding.objects.get(workspace=ws, source=_SOURCE, fingerprint="fp-1")
    assert finding.scan_run_id == str(run.id)


def test_reobservation_moves_provenance_to_the_newest_run(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    with django_capture_on_commit_callbacks(execute=True):
        first = _run(ws, [_finding("1")])
    with django_capture_on_commit_callbacks(execute=True):
        second = _run(ws, [_finding("1")])

    assert first.id != second.id
    finding = Finding.objects.get(workspace=ws, source=_SOURCE, fingerprint="fp-1")
    # Still ONE finding (dedup) — its provenance follows the LAST observation,
    # like last_seen_at.
    assert Finding.objects.filter(workspace=ws, source=_SOURCE).count() == 1
    assert finding.scan_run_id == str(second.id)


def test_runless_reobservation_keeps_the_previous_run_link(workspace_factory, django_capture_on_commit_callbacks):
    """A source with no run record (detector cycle / log ingest) re-observing the
    same fingerprint must not ERASE the provenance a spine run already stamped."""
    from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
        CeleryEventPublisher,
    )

    ws = workspace_factory()
    with django_capture_on_commit_callbacks(execute=True):
        run = _run(ws, [_finding("1")])

    original = _finding("1")
    with django_capture_on_commit_callbacks(execute=True):
        CeleryEventPublisher().publish(
            FindingObserved(
                workspace_id=ws.id,
                source=original.source,
                fingerprint=original.fingerprint,
                asset_urn=original.asset_urn,
                severity=original.severity.value,
                title=original.title,
                # scan_run_id deliberately left at its "" default.
            )
        )

    finding = Finding.objects.get(workspace=ws, source=_SOURCE, fingerprint="fp-1")
    assert finding.scan_run_id == str(run.id), "an empty scan_run_id must not erase existing provenance"
