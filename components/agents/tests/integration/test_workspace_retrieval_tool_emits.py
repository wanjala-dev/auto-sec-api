"""Integration test for the ``retrieve_workspace_context`` tool's
log + progress emits.

Exercises the Phase 2 wiring end-to-end:

1. A ``DeepRun`` is created so ``log_deep_event`` finds the run.
2. A ``DeepRunContext`` is built and stashed on the agent
   (``self._active_deep_run_context``) — this is what
   ``BaseAgent.execute`` does at the top of every call when the
   incoming context dict carries a ``deep_run_context``.
3. The retrieval tool's closure is invoked.
4. The test asserts ``DeepRunLog`` rows materialise: an info ("Searching
   workspace knowledge…"), a progress (20/100), then either an info +
   progress (success path) or a warn (no-index path) — depending on
   what the in-process pgvector adapter returns.

Avoids the langchain agent runtime (which would require an LLM key and
real prompt loop) — calls ``_build_workspace_retrieval_tool().func``
directly, which is the same closure the langchain Tool wraps.

See ``docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md`` Phase 2.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from components.agents.application.ports.deep_run_observability_port import (
    EVENT_TOOL_LOG,
    EVENT_TOOL_PROGRESS,
)
from components.agents.application.services.deep_run_context import (
    DeepRunContext,
    DeepRunContextOptions,
)
from components.agents.infrastructure.adapters.deep_run_log_observability_adapter import (
    DeepRunLogObservabilityAdapter,
)


@pytest.fixture
def deep_run(workspace_factory, user_factory):
    from infrastructure.persistence.ai.agents.models import DeepRun

    workspace = workspace_factory()
    user = user_factory()
    return DeepRun.objects.create(
        thread_id="test-retrieval-thread",
        plan_id="plan-retrieval",
        user=user,
        workspace=workspace,
        status=DeepRun.STATUS_RUNNING,
    )


@pytest.fixture
def deep_run_context(deep_run):
    return DeepRunContext(
        DeepRunLogObservabilityAdapter(),
        DeepRunContextOptions(
            thread_id=deep_run.thread_id,
            default_agent_type="financial_agent",
            default_tool_name=None,
        ),
    )


def _build_tool_with_stub_agent(workspace_id: str, deep_run_context: DeepRunContext):
    """Build the retrieval tool against a minimal stub that mimics the
    BaseAgent attributes the closure reads.

    The full BaseAgent has 1000+ lines of LangChain plumbing irrelevant
    here; the tool only needs ``self.workspace_id`` and the context
    slot. Using a stub keeps this test fast and isolated to the closure
    we're verifying.
    """
    from components.agents.infrastructure.adapters.langchain.base import BaseAgent

    class _Stub:
        # Bind just enough surface for ``_build_workspace_retrieval_tool``
        # to operate. The ``__class__`` of the bound method matters
        # because the inner closure reads ``self.workspace_id`` and
        # ``self._active_deep_run_context``.
        def __init__(self):
            self.workspace_id = workspace_id
            self._active_deep_run_context = deep_run_context

    stub = _Stub()
    return BaseAgent._build_workspace_retrieval_tool(stub)


@pytest.mark.django_db
class TestRetrievalToolEmits:
    def test_emits_searching_then_no_index_warn_when_pgvector_unavailable(
        self, deep_run, deep_run_context
    ):
        # In the test container pgvector is absent, so the adapter
        # ``_pgvector_available`` returns False and ``search`` returns
        # an empty list — the no-index path. Verify the warn emit.
        tool = _build_tool_with_stub_agent(
            str(deep_run.workspace_id), deep_run_context
        )
        result = tool.func("mission and story")

        assert "no indexed context" in result.lower()

        logs = list(deep_run.logs.order_by("created_at"))
        # Expect: searching info, 20% progress, no-index warn,
        # 100% progress. (Order based on the closure's emit
        # sequence above.)
        events = [(log.event_type, log.payload.get("severity"), log.tool_name) for log in logs]
        assert (EVENT_TOOL_LOG, "info", "retrieve_workspace_context") in events, events
        assert (EVENT_TOOL_LOG, "warn", "retrieve_workspace_context") in events, events
        assert any(e[0] == EVENT_TOOL_PROGRESS for e in events), events

    def test_emits_retrieved_chunks_summary_on_success_path(
        self, deep_run, deep_run_context
    ):
        # Patch the workspace_retrieval provider to return a fake
        # adapter whose ``search`` returns three deterministic chunks.
        # Verifies the success path's "Retrieved N chunks (X chars)"
        # info emit + 100% progress.
        from components.knowledge.application.ports.vector_store_port import (
            RetrievedChunk,
        )

        class _FakeAdapter:
            def search(self, *, workspace_id, query, k, viewer_role=None):
                return [
                    RetrievedChunk(
                        content="Mission: empower nonprofits with AI.",
                        metadata={"section_title": "mission"},
                        score=0.9,
                    ),
                    RetrievedChunk(
                        content="Story: founded 2025 in Nairobi.",
                        metadata={"section_title": "story"},
                        score=0.8,
                    ),
                    RetrievedChunk(
                        content="Sectors served: education, health, livelihoods.",
                        metadata={"section_title": "sectors"},
                        score=0.7,
                    ),
                ]

        with patch(
            "components.knowledge.application.providers.workspace_retrieval_provider.workspace_retrieval",
            return_value=_FakeAdapter(),
        ):
            tool = _build_tool_with_stub_agent(
                str(deep_run.workspace_id), deep_run_context
            )
            result = tool.func("mission and story")

        # Returned text contains chunk content (proves search did fire)
        assert "Mission" in result
        assert "Sectors" in result

        infos = [
            log
            for log in deep_run.logs.filter(event_type=EVENT_TOOL_LOG).order_by("created_at")
            if log.payload.get("severity") == "info"
        ]
        # Two info lines: "Searching..." and "Retrieved N chunks..."
        assert len(infos) >= 2
        retrieved_msg = next(
            (log for log in infos if "Retrieved" in log.payload.get("message", "")),
            None,
        )
        assert retrieved_msg is not None
        assert retrieved_msg.payload["chunks"] == 3
        # Total characters = sum of stripped content lengths.
        assert retrieved_msg.payload["characters"] > 0
        # 100% progress at end.
        progress_logs = list(
            deep_run.logs.filter(event_type=EVENT_TOOL_PROGRESS).order_by("created_at")
        )
        assert progress_logs[-1].payload["progress_percent"] == 100

    def test_empty_query_skips_emits_and_returns_helpful_message(
        self, deep_run, deep_run_context
    ):
        tool = _build_tool_with_stub_agent(
            str(deep_run.workspace_id), deep_run_context
        )
        result = tool.func("   ")

        assert "non-empty query" in result
        # No emits should fire on the empty-query early return.
        assert deep_run.logs.count() == 0

    def test_no_active_context_falls_back_to_noop_silently(
        self, deep_run
    ):
        # Stub has no ``_active_deep_run_context`` set — closure
        # uses noop_context() and produces zero log rows even though
        # the tool runs to completion.
        from components.agents.infrastructure.adapters.langchain.base import (
            BaseAgent,
        )

        class _Stub:
            workspace_id = str(deep_run.workspace_id)
            _active_deep_run_context = None

        tool = BaseAgent._build_workspace_retrieval_tool(_Stub())
        result = tool.func("mission")

        assert "no indexed context" in result.lower()
        # No deep-run logs because ctx fell back to noop.
        assert deep_run.logs.count() == 0
