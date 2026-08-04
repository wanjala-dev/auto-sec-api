"""The generic scan choreography emits the funnel's scan lifecycle events (ADR 0016).

``run_scan_and_ingest`` must emit exactly ONE ``ScanCompleted`` per run (the
anti-flood digest signal) alongside its ``FindingObserved`` dual-write, and the
``run_scan`` task must emit ``ScanFailed`` on its fail-loud path — the producer
side the notifications context turns into Slack messages.
"""

from __future__ import annotations

import pytest

from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
from components.shared_kernel.application.ports.scanner_port import ScanResult, ScanTarget
from components.shared_kernel.domain.events import FindingObserved, ScanCompleted, ScanFailed
from components.shared_kernel.domain.security import NormalizedFinding, Severity

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "container_security.trivy"


class _CapturingPublisher:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


def _finding(severity: Severity, suffix: str) -> NormalizedFinding:
    return NormalizedFinding(
        source=_SOURCE,
        fingerprint=f"fp-{suffix}",
        asset_urn=f"urn:image/repo:tag/{suffix}",
        severity=severity,
        title=f"CVE-2024-000{suffix} in openssl",
    )


class _StubScanner:
    def __init__(self, result):
        self._result = result

    def scan(self, target, on_progress=None):
        return self._result


class _ExplodingScanner:
    def scan(self, target, on_progress=None):
        raise RuntimeError("engine crashed")


def _result(findings):
    return ScanResult(
        findings=tuple(findings),
        engine="trivy",
        engine_version="0.58.0",
        total_checks=len(findings),
        passed_count=0,
        failed_count=len(findings),
    )


def test_run_emits_one_scan_completed_with_severity_counts(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    cap = _CapturingPublisher()
    findings = [_finding(Severity.CRITICAL, "1"), _finding(Severity.HIGH, "2"), _finding(Severity.HIGH, "3")]

    with django_capture_on_commit_callbacks(execute=True):
        run = run_scan_and_ingest(
            workspace_id=ws.id,
            source=_SOURCE,
            target=ScanTarget(identifier="repo/image:tag"),
            scanner=_StubScanner(_result(findings)),
            account_id="123456789012",
            event_publisher=cap,
        )

    observed = [e for e in cap.published if isinstance(e, FindingObserved)]
    completed = [e for e in cap.published if isinstance(e, ScanCompleted)]
    assert len(observed) == 3
    assert len(completed) == 1, "exactly ONE digest signal per scan run"
    digest = completed[0]
    assert digest.scan_id == str(run.id)
    assert digest.source == _SOURCE
    assert digest.engine == "trivy"
    assert digest.target_ref == "repo/image:tag"
    assert digest.account_id == "123456789012"
    assert (digest.critical, digest.high, digest.medium, digest.low) == (1, 2, 0, 0)
    assert digest.findings_observed == 3


def test_clean_run_still_emits_the_digest(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    cap = _CapturingPublisher()

    with django_capture_on_commit_callbacks(execute=True):
        run_scan_and_ingest(
            workspace_id=ws.id,
            source=_SOURCE,
            target=ScanTarget(identifier="repo/image:tag"),
            scanner=_StubScanner(_result([])),
            event_publisher=cap,
        )

    completed = [e for e in cap.published if isinstance(e, ScanCompleted)]
    assert len(completed) == 1
    assert completed[0].findings_observed == 0


def test_failed_run_emits_nothing_from_the_choreography(workspace_factory, django_capture_on_commit_callbacks):
    """The failure alert belongs to the task's fail-loud path, not the choreography —
    which must mark the run FAILED, emit no digest, and re-raise."""
    from infrastructure.persistence.scanning.models import ScanRun

    ws = workspace_factory()
    cap = _CapturingPublisher()

    with django_capture_on_commit_callbacks(execute=True), pytest.raises(RuntimeError):
        run_scan_and_ingest(
            workspace_id=ws.id,
            source=_SOURCE,
            target=ScanTarget(identifier="repo/image:tag"),
            scanner=_ExplodingScanner(),
            event_publisher=cap,
        )

    assert cap.published == []
    run = ScanRun.objects.get(workspace_id=ws.id)
    assert run.status == ScanRun.Status.FAILED


def test_run_scan_task_failure_publishes_scan_failed(workspace_factory, monkeypatch):
    import components.scanning.application.providers.scanner_registry as registry_mod
    from components.scanning.infrastructure.tasks import scan_tasks as tasks_mod
    from components.shared_kernel.infrastructure.adapters import celery_event_publisher as pub_mod

    ws = workspace_factory()
    published = []
    monkeypatch.setattr(registry_mod, "get_scanner", lambda source: _ExplodingScanner())
    monkeypatch.setattr(pub_mod.CeleryEventPublisher, "publish", lambda self, event: published.append(event))

    result = tasks_mod.run_scan.apply(
        kwargs={
            "source": _SOURCE,
            "workspace_id": str(ws.id),
            "target_ref": "repo/image:tag",
            "account_id": "123456789012",
        }
    ).get()

    assert result == {"success": False, "error": "scan_failed"}
    failed = [e for e in published if isinstance(e, ScanFailed)]
    assert len(failed) == 1
    event = failed[0]
    assert event.workspace_id == ws.id
    assert event.source == _SOURCE
    assert event.engine == "trivy"
    assert event.target_ref == "repo/image:tag"
    assert event.account_id == "123456789012"
    assert event.run_id, "a per-attempt identity is required so recurring failures re-alert"
    # Coarse redaction-safe token — never the raw exception string.
    assert event.reason == "scan engine failure"
    assert "engine crashed" not in event.reason
