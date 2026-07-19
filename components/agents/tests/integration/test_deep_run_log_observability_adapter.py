"""Integration tests for ``DeepRunLogObservabilityAdapter``.

End-to-end against a real ``DeepRun`` row so the existing
``log_deep_event`` helper can match by ``thread_id`` and persist a
``DeepRunLog``. We don't assert on the realtime signal bridge here —
that's exercised separately by the existing realtime tests — but the
``DeepRunLog.post_save`` hook will fire as a side effect, which is
fine and proves the adapter integrates cleanly with the existing
publish path.

See ``docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md`` Phase 1.
"""
from __future__ import annotations

import pytest

from components.agents.application.ports.deep_run_observability_port import (
    EVENT_TOOL_LOG,
    EVENT_TOOL_PROGRESS,
)
from components.agents.infrastructure.adapters.deep_run_log_observability_adapter import (
    DeepRunLogObservabilityAdapter,
)


@pytest.fixture
def deep_run(workspace_factory, user_factory):
    """Materialise a DeepRun row matching a known thread_id so
    ``log_deep_event`` finds it. Returns the run; callers usually only
    need its thread_id but having the full object lets them assert on
    the related logs queryset.
    """
    from infrastructure.persistence.ai.agents.models import DeepRun

    workspace = workspace_factory()
    user = user_factory()
    return DeepRun.objects.create(
        thread_id="test-thread-1",
        plan_id="plan-1",
        user=user,
        workspace=workspace,
        status=DeepRun.STATUS_RUNNING,
    )


@pytest.mark.django_db
class TestDeepRunLogObservabilityAdapter:
    def test_emit_log_persists_a_tool_log_row_with_message_and_severity(
        self, deep_run
    ):
        adapter = DeepRunLogObservabilityAdapter()
        adapter.emit_log(
            thread_id=deep_run.thread_id,
            message="Searching workspace knowledge…",
            tool_name="workspace_rag",
            agent_type="financial_agent",
        )
        log = deep_run.logs.filter(event_type=EVENT_TOOL_LOG).first()
        assert log is not None
        assert log.tool_name == "workspace_rag"
        assert log.agent_type == "financial_agent"
        assert log.payload["message"] == "Searching workspace knowledge…"
        assert log.payload["severity"] == "info"

    def test_emit_log_warn_severity_passes_through(self, deep_run):
        adapter = DeepRunLogObservabilityAdapter()
        adapter.emit_log(
            thread_id=deep_run.thread_id,
            message="Vector store returned 0 hits",
            severity="warn",
        )
        log = deep_run.logs.filter(event_type=EVENT_TOOL_LOG).first()
        assert log.payload["severity"] == "warn"

    def test_emit_log_caller_payload_merges_with_message_and_severity(
        self, deep_run
    ):
        adapter = DeepRunLogObservabilityAdapter()
        adapter.emit_log(
            thread_id=deep_run.thread_id,
            message="Retrieved chunks",
            payload={"chunks": 12, "chars": 6940},
        )
        log = deep_run.logs.filter(event_type=EVENT_TOOL_LOG).first()
        assert log.payload["message"] == "Retrieved chunks"
        assert log.payload["chunks"] == 12
        assert log.payload["chars"] == 6940

    def test_emit_progress_persists_tool_progress_row_with_percent(
        self, deep_run
    ):
        adapter = DeepRunLogObservabilityAdapter()
        adapter.emit_progress(
            thread_id=deep_run.thread_id,
            current=80,
            total=100,
            message="Generating LLM summary…",
            tool_name="workspace_rag",
        )
        log = deep_run.logs.filter(event_type=EVENT_TOOL_PROGRESS).first()
        assert log is not None
        assert log.tool_name == "workspace_rag"
        assert log.payload["current"] == 80.0
        assert log.payload["total"] == 100.0
        assert log.payload["progress_percent"] == 80
        assert log.payload["message"] == "Generating LLM summary…"

    def test_emit_progress_without_total_omits_progress_percent(
        self, deep_run
    ):
        adapter = DeepRunLogObservabilityAdapter()
        adapter.emit_progress(
            thread_id=deep_run.thread_id,
            current=42,
        )
        log = deep_run.logs.filter(event_type=EVENT_TOOL_PROGRESS).first()
        assert log is not None
        assert log.payload["current"] == 42.0
        assert log.payload["total"] is None
        assert "progress_percent" not in log.payload

    def test_emit_progress_clamps_percent_to_0_100_range(self, deep_run):
        adapter = DeepRunLogObservabilityAdapter()
        # Over-shooting current shouldn't produce > 100.
        adapter.emit_progress(thread_id=deep_run.thread_id, current=150, total=100)
        log = deep_run.logs.filter(event_type=EVENT_TOOL_PROGRESS).first()
        assert log.payload["progress_percent"] == 100

    def test_emit_log_with_unknown_thread_id_is_silent_noop(self, deep_run):
        # Adapter early-returns when thread_id is None or empty.
        adapter = DeepRunLogObservabilityAdapter()
        adapter.emit_log(thread_id=None, message="dropped")
        adapter.emit_log(thread_id="", message="also dropped")
        adapter.emit_log(thread_id="no-such-run", message="also dropped")
        # No DeepRunLog rows should have been created on the fixture's
        # run for those calls. log_deep_event itself silently no-ops
        # for the "no-such-run" case via its inner filter().first().
        assert deep_run.logs.filter(event_type=EVENT_TOOL_LOG).count() == 0

    def test_emit_progress_with_unknown_thread_id_is_silent_noop(self, deep_run):
        adapter = DeepRunLogObservabilityAdapter()
        adapter.emit_progress(thread_id=None, current=1, total=10)
        adapter.emit_progress(thread_id="", current=1, total=10)
        adapter.emit_progress(thread_id="no-such-run", current=1, total=10)
        assert deep_run.logs.filter(event_type=EVENT_TOOL_PROGRESS).count() == 0
