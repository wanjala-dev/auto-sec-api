"""Integration tests for the temporal log-pattern analyzer (#47).

Exercises the *over time* behaviour end-to-end with a real DB (the
``LogPatternRollup`` upserts) but the S3 read stubbed at the
``iter_window_records`` boundary — no AWS. Proves:

* a high-frequency pattern is NOT surfaced on its first observation (blip
  suppression) and IS once sustained across ``min_runs`` runs;
* the finding carries the full evidence contract (kind/frequency/evidence/
  blast_radius/fingerprint) with empty recommendation (left for the agent);
* classification routes beat noise → periodic_task and housekeeping → health_check;
* the fingerprint is signature-stable across runs (idempotent card dedupe).
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.log_ingest_service import LogRecord

_ANALYZER = "components.integrations.application.log_pattern_analyzer_service"


def _beat_line(task="workflow.run_due_schedules"):
    msg = f"INFO Scheduler: Sending due task {task} ({task})"
    return LogRecord(service="celery_beat", level="INFO", message=msg, raw=msg)


def _health_line():
    msg = "Background saving terminated with success"
    return LogRecord(service="redis", level="INFO", message=msg, raw=msg)


def _window(beat_n=12, health_n=25):
    """One synthetic window: an over-scheduled beat task + redis housekeeping."""
    recs = [(_beat_line(), "logs/2026/window.json.gz") for _ in range(beat_n)]
    recs += [(_health_line(), "logs/2026/window.json.gz") for _ in range(health_n)]
    return recs


@pytest.fixture
def connected_workspace(workspace_factory):
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    workspace = workspace_factory()
    AwsOrganizationConnection.objects.create(
        workspace=workspace,
        management_account_id="123456789012",
        role_name="AutoSecAuditRole",
        external_id=f"ext-{workspace.id}",
        trail_s3_bucket="acme-logs",
        status="connected",
    )
    return workspace


@pytest.mark.django_db
class TestLogPatternAnalyzer:
    def test_sustained_pattern_surfaces_only_after_min_runs(self, connected_workspace):
        from components.integrations.application.log_pattern_analyzer_service import (
            aggregate_workspace_log_patterns,
        )
        from infrastructure.persistence.integrations.models import LogPatternRollup

        with mock.patch(f"{_ANALYZER}.iter_window_records", return_value=_window()):
            first = aggregate_workspace_log_patterns(connected_workspace.id, min_runs=2)
        # First observation is a blip — nothing surfaced yet, but the rollup exists.
        assert first == []
        beat_rollup = LogPatternRollup.objects.get(
            workspace=connected_workspace, signature="celery_beat|beat|workflow.run_due_schedules"
        )
        assert beat_rollup.runs_observed == 1
        assert beat_rollup.kind == "periodic_task"

        # Second run — now sustained; the over-scheduled task is surfaced.
        with mock.patch(f"{_ANALYZER}.iter_window_records", return_value=_window()):
            second = aggregate_workspace_log_patterns(connected_workspace.id, min_runs=2)

        kinds = {f.kind for f in second}
        assert "periodic_task" in kinds
        assert "health_check" in kinds
        beat_finding = next(f for f in second if f.kind == "periodic_task")
        assert beat_finding.subject == "workflow.run_due_schedules"
        assert beat_finding.runs_observed == 2

    def test_finding_carries_evidence_contract(self, connected_workspace):
        from components.integrations.application.log_pattern_analyzer_service import (
            aggregate_workspace_log_patterns,
        )

        for _ in range(2):
            with mock.patch(f"{_ANALYZER}.iter_window_records", return_value=_window()):
                findings = aggregate_workspace_log_patterns(connected_workspace.id, min_runs=2)

        beat = next(f for f in findings if f.kind == "periodic_task")
        contract = beat.as_contract()
        assert contract["kind"] == "periodic_task"
        assert contract["signal"]
        assert contract["evidence"], "evidence[] must be present"
        assert contract["frequency"]["last_window"] == 12
        assert contract["frequency"]["runs_observed"] == 2
        assert contract["blast_radius"]["service"] == "celery_beat"
        # Recommendation left empty for the optimization agent (LLM-after).
        assert contract["recommendation"] == ""
        assert contract["suggested_fix"] == ""
        assert contract["fingerprint"].startswith("logopt:")
        assert contract["triage"]["status"] == "pending"

    def test_fingerprint_is_signature_stable_across_runs(self, connected_workspace):
        from components.integrations.application.log_pattern_analyzer_service import (
            aggregate_workspace_log_patterns,
        )

        fps = []
        for _ in range(3):
            with mock.patch(f"{_ANALYZER}.iter_window_records", return_value=_window()):
                findings = aggregate_workspace_log_patterns(connected_workspace.id, min_runs=2)
            beat = [f for f in findings if f.kind == "periodic_task"]
            if beat:
                fps.append(beat[0].fingerprint)
        # Same over-scheduled task → same fingerprint every run (idempotent dedupe).
        assert len(set(fps)) == 1

    def test_no_connection_returns_empty(self, workspace_factory):
        from components.integrations.application.log_pattern_analyzer_service import (
            aggregate_workspace_log_patterns,
        )

        ws = workspace_factory()  # no AwsOrganizationConnection
        assert aggregate_workspace_log_patterns(ws.id) == []


@pytest.mark.django_db
class TestClassification:
    def test_classify_and_signature(self):
        from components.integrations.application.log_pattern_analyzer_service import _classify, _signature

        beat = "INFO Scheduler: Sending due task foo.bar (foo.bar)"
        assert _classify("celery_beat", beat) == ("periodic_task", "foo.bar")
        # Signature keys on the task path only — schedule ids/timestamps vary.
        assert _signature("celery_beat", beat) == "celery_beat|beat|foo.bar"
        assert _classify("web", "GET /api/health/ 200")[0] == "health_check"
        assert _classify("redis", "Background saving started by pid 123")[0] == "health_check"
