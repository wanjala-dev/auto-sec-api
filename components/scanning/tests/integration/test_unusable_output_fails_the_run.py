"""End-to-end proof of the guard at the SPINE: unusable output ⇒ a FAILED ScanRun.

``test_engine_output_integrity`` proves each adapter raises. This proves what that
raise actually *buys*: the ``ScanRun`` row an operator and the HUD read says FAILED with
an honest error — not COMPLETED with zero findings. That distinction IS the feature; a
loud exception that still left a COMPLETED row would fix nothing.

The counter-case is asserted just as hard: a genuinely clean scan (engine exit 0, valid
and complete but empty result set) must still COMPLETE normally. A guard that fails
honest clean scans would be a different, equally bad bug — every clean account crying wolf.
"""

from __future__ import annotations

import pytest

from components.scanning.domain.errors import IncompleteScanOutputError
from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
from components.shared_kernel.application.ports.scanner_port import ScanResult, ScanTarget

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "cloud_posture.prowler"


class _TruncatedOutputScanner:
    """The real failure: the engine exited 0, but its output was cut short.

    Modelled on the production path — the adapter's document guard raises while the
    Job itself reported success, which is precisely why exit code alone cannot catch it.
    """

    def scan(self, target, on_progress=None):
        raise IncompleteScanOutputError(
            "prowler output is not a complete JSON document (10.00 MiB, opens with '[' "
            "but never closes with ']' — the output was TRUNCATED)"
        )


class _CleanScanner:
    """Engine exit 0, valid + complete result document, no findings. A real answer."""

    def scan(self, target, on_progress=None):
        return ScanResult(findings=(), engine="prowler", engine_version="5.36.0", total_checks=412, passed_count=412)


def _target() -> ScanTarget:
    return ScanTarget(identifier="123456789012", params={"provider": "aws"})


def test_truncated_output_records_a_failed_run_not_a_clean_one(workspace_factory):
    from infrastructure.persistence.scanning.models import ScanRun

    ws = workspace_factory()

    # Fail loud: the spine re-raises so the caller (task) reacts — it does not swallow.
    with pytest.raises(IncompleteScanOutputError):
        run_scan_and_ingest(workspace_id=ws.id, source=_SOURCE, target=_target(), scanner=_TruncatedOutputScanner())

    run = ScanRun.objects.get(workspace_id=ws.id, source=_SOURCE)
    assert run.status == ScanRun.Status.FAILED
    assert run.completed_at is not None
    # The error must name the cause — this row is what an operator reads at 2am.
    assert "TRUNCATED" in run.error


def test_truncated_output_emits_no_findings_and_no_scan_completed(
    workspace_factory, django_capture_on_commit_callbacks
):
    """A mutilated scan must not reach the findings SSOT or the digest at all.

    Emitting ScanCompleted(findings_observed=0) would tell the Slack digest and the HUD
    "we looked, it's clean" — the exact lie the FAILED row exists to prevent.
    """
    published = []

    class _Publisher:
        def publish(self, event):
            published.append(event)

    ws = workspace_factory()
    with django_capture_on_commit_callbacks(execute=True), pytest.raises(IncompleteScanOutputError):
        run_scan_and_ingest(
            workspace_id=ws.id,
            source=_SOURCE,
            target=_target(),
            scanner=_TruncatedOutputScanner(),
            event_publisher=_Publisher(),
        )

    assert published == []


def test_genuinely_clean_scan_still_completes_normally(workspace_factory, django_capture_on_commit_callbacks):
    from infrastructure.persistence.scanning.models import ScanRun

    ws = workspace_factory()
    with django_capture_on_commit_callbacks(execute=True):
        run = run_scan_and_ingest(workspace_id=ws.id, source=_SOURCE, target=_target(), scanner=_CleanScanner())

    run.refresh_from_db()
    assert run.status == ScanRun.Status.COMPLETED
    assert not run.error
    # The counts prove the engine really looked — 412 checks passed, zero findings.
    assert run.total_checks == 412
    assert run.passed_count == 412


def test_engine_non_zero_exit_still_fails_the_run(workspace_factory):
    """The pre-existing fail-loud path stays intact (no regression from the new guard)."""
    from components.scanning.domain.errors import ScanExecutionError
    from infrastructure.persistence.scanning.models import ScanRun

    class _CrashedScanner:
        def scan(self, target, on_progress=None):
            raise ScanExecutionError("Prowler aws scan of 123456789012 failed (exit_code=1, timed_out=False)")

    ws = workspace_factory()
    with pytest.raises(ScanExecutionError):
        run_scan_and_ingest(workspace_id=ws.id, source=_SOURCE, target=_target(), scanner=_CrashedScanner())

    run = ScanRun.objects.get(workspace_id=ws.id, source=_SOURCE)
    assert run.status == ScanRun.Status.FAILED
    assert "exit_code=1" in run.error
