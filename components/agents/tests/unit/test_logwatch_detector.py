"""Unit tests for the Log-Watch detector — the evidence-contract sensor.

Pure unit: the deterministic scan (``scan_workspace_for_errors``) is stubbed at
the integrations-application boundary, so no AWS/S3. Asserts the detector emits
an evidence-bearing ``DetectorResult`` per finding (the §14.9 contract) routed
to the triage agent, and never touches an LLM.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from components.agents.infrastructure.adapters.actions.detectors.logwatch import (
    AiFindingRouterDetector,
    LogOptimizationDetector,
    LogWatchErrorDetector,
)
from components.integrations.application.log_ingest_service import ErrorFinding
from components.integrations.application.log_pattern_analyzer_service import OptimizationFinding


def _finding(fingerprint="abc123", severity="high"):
    return ErrorFinding(
        fingerprint=fingerprint,
        service="celery_worker",
        level="ERROR",
        severity=severity,
        signal="ERROR in celery_worker",
        message="cannot import name 'AiEmbeddingsProvider'",
        evidence=[{"type": "log_line", "detail": "Traceback ... ImportError"}],
        blast_radius={"service": "celery_worker", "level": "ERROR", "window_records": 271},
        confidence="high",
    )


def _ctx(workspace_id="ws-1"):
    return SimpleNamespace(workspace_id=workspace_id, invoke_agent=None)


def test_detector_emits_evidence_bearing_result_per_finding():
    with mock.patch(
        "components.integrations.application.log_ingest_service.scan_workspace_for_errors",
        return_value=[_finding("fp1"), _finding("fp2")],
    ):
        results = list(LogWatchErrorDetector().execute(_ctx()))

    assert len(results) == 2
    r = results[0]
    # Routed to the triage specialist, tagged as a log_watch finding.
    assert r.action_type == "log_watch"
    assert r.agent_type == "triage_agent"
    # The evidence contract rides on the payload (persist_finding_as_task stores
    # it on Task.metadata.payload; the serializer surfaces it as log_watch).
    assert r.payload["signal"] == "ERROR in celery_worker"
    assert r.payload["confidence"] == "high"
    assert r.payload["evidence"], "evidence[] must be present for a trustable finding"
    assert r.payload["blast_radius"]["service"] == "celery_worker"
    # probable_cause / suggested_fix are left for the triage agent (LLM-after).
    assert r.payload["probable_cause"] == ""
    assert r.payload["suggested_fix"] == ""
    # Content fingerprint drives idempotent dedupe at the cycle.
    assert r.payload["lookup_key"] == "fp1"
    # Impact score maps from severity (high → 70).
    assert r.metadata["impact_score"] == 70


def test_detector_no_findings_emits_nothing():
    with mock.patch(
        "components.integrations.application.log_ingest_service.scan_workspace_for_errors",
        return_value=[],
    ):
        results = list(LogWatchErrorDetector().execute(_ctx()))
    assert results == []


def test_detector_never_calls_an_llm():
    # The sensor is deterministic (POC hard rule). If it tried to build an LLM
    # the provider would be hit — assert it is not, even with findings present.
    with (
        mock.patch(
            "components.integrations.application.log_ingest_service.scan_workspace_for_errors",
            return_value=[_finding()],
        ),
        mock.patch("components.knowledge.application.providers.ai_llm_provider.AILlmProvider") as llm_provider,
    ):
        list(LogWatchErrorDetector().execute(_ctx()))
    llm_provider.assert_not_called()


def _opt_finding(fingerprint="logopt:abc", kind="periodic_task"):
    return OptimizationFinding(
        fingerprint=fingerprint,
        service="celery_beat",
        kind=kind,
        signature="celery_beat|beat|workflow.run_due_schedules",
        subject="workflow.run_due_schedules",
        signal="'workflow.run_due_schedules' fired 41× in the last window — likely over-scheduled.",
        last_window_count=41,
        runs_observed=3,
        total_count=120,
        peak_window_count=41,
        evidence=[{"type": "frequency", "detail": "41 occurrences in the last window"}],
        blast_radius={"service": "celery_beat", "kind": kind, "window_records": 500, "share_pct": 8.2},
        confidence="high",
    )


def test_optimization_detector_emits_contract_routed_to_optimization_agent():
    with mock.patch(
        "components.integrations.application.log_pattern_analyzer_service.aggregate_workspace_log_patterns",
        return_value=[_opt_finding("logopt:1"), _opt_finding("logopt:2", kind="health_check")],
    ):
        results = list(LogOptimizationDetector().execute(_ctx()))

    assert len(results) == 2
    r = results[0]
    # New finding KIND → distinct source_type + specialist (the scale proof).
    assert r.action_type == "log_optimization"
    assert r.agent_type == "optimization_agent"
    assert r.payload["kind"] == "periodic_task"
    assert r.payload["frequency"]["last_window"] == 41
    assert r.payload["evidence"], "evidence[] must ride on the finding"
    # Recommendation left for the optimization agent (LLM-after-detection).
    assert r.payload["recommendation"] == ""
    assert r.payload["lookup_key"] == "logopt:1"


def test_optimization_detector_no_findings_emits_nothing():
    with mock.patch(
        "components.integrations.application.log_pattern_analyzer_service.aggregate_workspace_log_patterns",
        return_value=[],
    ):
        assert list(LogOptimizationDetector().execute(_ctx())) == []


def test_optimization_detector_never_calls_an_llm():
    with (
        mock.patch(
            "components.integrations.application.log_pattern_analyzer_service.aggregate_workspace_log_patterns",
            return_value=[_opt_finding()],
        ),
        mock.patch("components.knowledge.application.providers.ai_llm_provider.AILlmProvider") as llm_provider,
    ):
        list(LogOptimizationDetector().execute(_ctx()))
    llm_provider.assert_not_called()


def test_router_routes_both_log_source_types():
    # The router owns error AND optimization findings — proving a new finding
    # kind is picked up by adding its source_type, with no dispatch-logic change.
    assert "ai.log_watch" in AiFindingRouterDetector.ROUTABLE_SOURCE_TYPES
    assert "ai.log_optimization" in AiFindingRouterDetector.ROUTABLE_SOURCE_TYPES


def test_triage_router_no_pending_is_noop():
    # With no pending findings the router must not invoke any agent. The router
    # query is ``filter(...).filter(not_triaged_filter()).only(...)`` (NULL-safe
    # not-handled filter pushed into the DB) — resolves to empty here.
    empty_qs = mock.Mock()
    empty_qs.filter.return_value.only.return_value = []
    with mock.patch("infrastructure.persistence.project.models.Task") as task_model:
        task_model.objects.filter.return_value = empty_qs
        ctx = _ctx()
        ctx.invoke_agent = mock.Mock()
        assert list(AiFindingRouterDetector().execute(ctx)) == []
        ctx.invoke_agent.assert_not_called()
