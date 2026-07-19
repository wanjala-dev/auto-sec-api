"""Unit tests for ``DeepRunContext`` and ``NoopDeepRunContext``.

Pure application-layer behaviour — no DB, no Django imports. The tests
use a hand-rolled fake port to assert the context translates in-tool
calls into the right port invocations with the right payloads.

See ``docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md`` Phase 1.
"""
from __future__ import annotations

import pytest

from components.agents.application.ports.deep_run_observability_port import (
    DeepRunObservabilityPort,
)
from components.agents.application.services.deep_run_context import (
    DeepRunContext,
    DeepRunContextOptions,
    NoopDeepRunContext,
    noop_context,
)


class _FakeObservabilityPort(DeepRunObservabilityPort):
    """Captures every emit call so the test can assert on them.

    Uses two lists keyed by event type so order + cardinality + payload
    are all introspectable. Every kwarg the production port accepts is
    recorded verbatim — no normalisation, no defaults.
    """

    def __init__(self) -> None:
        self.logs: list[dict] = []
        self.progress: list[dict] = []

    def emit_log(self, **kwargs):
        self.logs.append(kwargs)

    def emit_progress(self, **kwargs):
        self.progress.append(kwargs)


@pytest.mark.unit
class TestDeepRunContext:
    def _build(
        self,
        thread_id: str | None = "thread-1",
        default_agent_type: str | None = "financial_agent",
        default_tool_name: str | None = "workspace_rag",
    ) -> tuple[DeepRunContext, _FakeObservabilityPort]:
        port = _FakeObservabilityPort()
        ctx = DeepRunContext(
            port,
            DeepRunContextOptions(
                thread_id=thread_id,
                default_agent_type=default_agent_type,
                default_tool_name=default_tool_name,
            ),
        )
        return ctx, port

    def test_info_calls_emit_log_with_info_severity_and_defaults(self):
        ctx, port = self._build()
        ctx.info("Searching workspace knowledge…")
        assert len(port.logs) == 1
        call = port.logs[0]
        assert call["thread_id"] == "thread-1"
        assert call["message"] == "Searching workspace knowledge…"
        assert call["tool_name"] == "workspace_rag"
        assert call["agent_type"] == "financial_agent"
        assert call["severity"] == "info"
        assert call["payload"] is None

    def test_info_explicit_tool_name_overrides_default(self):
        ctx, port = self._build()
        ctx.info("…", tool_name="override_tool")
        assert port.logs[0]["tool_name"] == "override_tool"

    def test_info_payload_passes_through_unchanged(self):
        ctx, port = self._build()
        ctx.info("Retrieved chunks", payload={"chunks": 12, "chars": 6940})
        assert port.logs[0]["payload"] == {"chunks": 12, "chars": 6940}

    def test_warn_calls_emit_log_with_warn_severity(self):
        ctx, port = self._build()
        ctx.warn("Vector store returned 0 hits")
        assert len(port.logs) == 1
        assert port.logs[0]["severity"] == "warn"
        assert port.logs[0]["message"] == "Vector store returned 0 hits"

    def test_report_progress_with_total_passes_both_values(self):
        ctx, port = self._build()
        ctx.report_progress(80, 100, message="Generating LLM summary…")
        assert len(port.progress) == 1
        call = port.progress[0]
        assert call["current"] == 80
        assert call["total"] == 100
        assert call["message"] == "Generating LLM summary…"
        assert call["tool_name"] == "workspace_rag"
        assert call["agent_type"] == "financial_agent"

    def test_report_progress_without_total_passes_none(self):
        ctx, port = self._build()
        ctx.report_progress(42)
        call = port.progress[0]
        assert call["current"] == 42
        assert call["total"] is None
        # message is optional and not provided here
        assert call["message"] is None

    def test_report_progress_explicit_tool_name_overrides_default(self):
        ctx, port = self._build()
        ctx.report_progress(10, 100, tool_name="other_tool")
        assert port.progress[0]["tool_name"] == "other_tool"

    def test_no_default_tool_name_propagates_none(self):
        ctx, port = self._build(default_tool_name=None)
        ctx.info("hello")
        assert port.logs[0]["tool_name"] is None

    def test_thread_id_passes_through_even_when_none(self):
        # Construct a context with no live thread — the port should
        # still receive the call (with thread_id=None) so the adapter
        # can decide what to do (the production adapter drops it).
        ctx, port = self._build(thread_id=None)
        ctx.info("…")
        ctx.report_progress(1, 1)
        assert port.logs[0]["thread_id"] is None
        assert port.progress[0]["thread_id"] is None


@pytest.mark.unit
class TestNoopDeepRunContext:
    def test_info_is_silent(self):
        ctx = NoopDeepRunContext()
        # No exception, no return value, no port to assert on.
        assert ctx.info("hello") is None
        assert ctx.info("with kwargs", payload={"x": 1}) is None

    def test_warn_is_silent(self):
        ctx = NoopDeepRunContext()
        assert ctx.warn("oops") is None

    def test_report_progress_is_silent(self):
        ctx = NoopDeepRunContext()
        assert ctx.report_progress(5, 10) is None
        assert ctx.report_progress(5) is None

    def test_noop_context_singleton_is_a_noop_instance(self):
        ctx = noop_context()
        assert isinstance(ctx, NoopDeepRunContext)
        # Returning the singleton is an optimisation; assert identity
        # so we don't accidentally start handing out fresh objects.
        assert noop_context() is ctx
