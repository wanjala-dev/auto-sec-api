"""Unit tests for ``_prefetch_retrieved_context`` and its injection into
the deep planner pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from components.agents.infrastructure.services.deep_service import (
    _prefetch_retrieved_context,
    plan_and_create_project,
    plan_and_run_with_llm,
)
from components.knowledge.application.ports.vector_store_port import RetrievedChunk


class TestPrefetchRetrievedContext:
    def test_returns_empty_for_blank_workspace(self):
        assert _prefetch_retrieved_context(workspace_id=None, goal="tldr") == []
        assert _prefetch_retrieved_context(workspace_id="", goal="tldr") == []

    def test_returns_empty_for_blank_goal(self):
        assert _prefetch_retrieved_context(workspace_id="ws-1", goal="") == []
        assert _prefetch_retrieved_context(workspace_id="ws-1", goal="   ") == []

    def test_serialises_chunks_with_section_and_score(self):
        fake_port = MagicMock()
        fake_port.search.return_value = [
            RetrievedChunk(
                content="Mission: Literacy for all.",
                metadata={
                    "section": "mission",
                    "section_title": "Mission & story",
                },
                score=0.91234,
            ),
        ]
        with patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ):
            result = _prefetch_retrieved_context(
                workspace_id="ws-1", goal="mission"
            )

        assert result == [
            {
                "section": "mission",
                "section_title": "Mission & story",
                "content": "Mission: Literacy for all.",
                "score": 0.9123,
                # SEE-200 — serialized retrieved chunks carry the index-time
                # injection flag; an unflagged chunk is untrusted=False.
                "untrusted": False,
            }
        ]

    def test_swallows_retrieval_backend_errors(self):
        fake_port = MagicMock()
        fake_port.search.side_effect = RuntimeError("pg down")
        with patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ):
            assert (
                _prefetch_retrieved_context(workspace_id="ws-1", goal="mission")
                == []
            )


class TestRerankMinScoreFromEnv:
    """The ``KNOWLEDGE_RERANK_MIN_SCORE`` env var is the precision
    knob from the 2026-06-10 baseline. Verify the env reader is
    defensive: malformed values must not break retrieval.

    Contract changed 2026-06-11 (task #84): the "no filter"
    sentinel is now ``None``, not ``0.0``, because cross-encoder
    logits skew negative on our corpus and 0.0 is now a real
    (aggressive) threshold.
    """

    def _read(self, value):
        from components.agents.infrastructure.services.deep_service import (
            _rerank_min_score_from_env,
        )
        import os

        if value is None:
            os.environ.pop("KNOWLEDGE_RERANK_MIN_SCORE", None)
        else:
            os.environ["KNOWLEDGE_RERANK_MIN_SCORE"] = value
        try:
            return _rerank_min_score_from_env()
        finally:
            os.environ.pop("KNOWLEDGE_RERANK_MIN_SCORE", None)

    def test_unset_returns_none(self):
        """Unset env var must signal 'no filter' so existing prod
        behavior is unchanged."""
        assert self._read(None) is None

    def test_empty_string_returns_none(self):
        assert self._read("") is None

    def test_valid_positive_float_parsed(self):
        assert self._read("1.5") == 1.5
        assert self._read("0.25") == 0.25

    def test_valid_zero_parsed_as_threshold(self):
        """0.0 is no longer the no-filter sentinel — it's now a real
        (aggressive) threshold for cross-encoder logits."""
        assert self._read("0.0") == 0.0

    def test_valid_negative_float_parsed(self):
        """Negative thresholds are the whole point of this contract
        change — cross-encoder logits skew negative on our corpus,
        so a threshold of -3.0 drops only the irrelevant tail."""
        assert self._read("-3.0") == -3.0
        assert self._read("-0.001") == -0.001

    def test_malformed_value_falls_back_to_none(self):
        """A typoed env var must not crash retrieval — every chat
        call hits this path, so silent fall-back is the correct
        failure mode (matches the rest of the prefetch pipeline)."""
        assert self._read("not-a-number") is None
        assert self._read("1.0.0") is None


class TestPlanAndRunInjectsRetrievedContext:
    def test_planner_receives_retrieved_context_in_extra_context(self):
        fake_port = MagicMock()
        fake_port.search.return_value = [
            RetrievedChunk(
                content="Workspace facts.",
                metadata={"section_title": "Workspace identity"},
                score=0.8,
            ),
        ]

        fake_pack = MagicMock()
        fake_pack.slug = "default"
        fake_pack.plan_planner = MagicMock(return_value=MagicMock())
        fake_pack.executor = MagicMock(return_value={"state": "ok"})

        with patch(
            "components.agents.infrastructure.services.deep_service._resolve_sector_pack",
            return_value=(None, None),
        ), patch(
            "components.agents.infrastructure.services.deep_service.get_deep_pack",
            return_value=fake_pack,
        ), patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ):
            plan_and_run_with_llm(
                goal="tldr",
                plan_id="pid",
                agent_type="workspace_agent",
                user_id="u",
                workspace_id="ws-1",
            )

        fake_pack.plan_planner.assert_called_once()
        kwargs = fake_pack.plan_planner.call_args.kwargs
        retrieved = kwargs["extra_context"].get("retrieved_context")
        assert retrieved
        assert retrieved[0]["content"] == "Workspace facts."

    def test_planner_does_not_receive_retrieved_context_when_none_found(self):
        fake_port = MagicMock()
        fake_port.search.return_value = []

        fake_pack = MagicMock()
        fake_pack.slug = "default"
        fake_pack.plan_planner = MagicMock(return_value=MagicMock())
        fake_pack.executor = MagicMock(return_value={"state": "ok"})

        with patch(
            "components.agents.infrastructure.services.deep_service._resolve_sector_pack",
            return_value=(None, None),
        ), patch(
            "components.agents.infrastructure.services.deep_service.get_deep_pack",
            return_value=fake_pack,
        ), patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ):
            plan_and_run_with_llm(
                goal="tldr",
                plan_id="pid",
                agent_type="workspace_agent",
                user_id="u",
                workspace_id="ws-1",
            )

        kwargs = fake_pack.plan_planner.call_args.kwargs
        assert "retrieved_context" not in kwargs["extra_context"]


class TestPlanAndCreateProjectInjectsRetrievedContext:
    """Tier 1 #3 — ``plan_and_create_project`` was historically the only
    deep-planner entry point that skipped the RAG prefetch.  Project
    plans were built without grounding even when the workspace had an
    embedded mission / sector / categories.  These tests pin the
    prefetch path so a future refactor can't silently re-open the gap.
    See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 1 #3.
    """

    def _patches(self, fake_port, fake_pack):
        return (
            patch(
                "components.agents.infrastructure.services."
                "deep_service._resolve_sector_pack",
                return_value=(None, None),
            ),
            patch(
                "components.agents.infrastructure.services."
                "deep_service.get_deep_pack",
                return_value=fake_pack,
            ),
            patch(
                "components.agents.infrastructure.services."
                "deep_service.run_project_creation",
                return_value={"project_id": "p-1"},
            ),
            patch(
                "components.knowledge.application.providers."
                "workspace_retrieval_provider.workspace_retrieval",
                return_value=fake_port,
            ),
        )

    def test_project_planner_receives_retrieved_context(self):
        fake_port = MagicMock()
        fake_port.search.return_value = [
            RetrievedChunk(
                content="Sprouted Roots is a literacy nonprofit.",
                metadata={"section_title": "Workspace identity"},
                score=0.88,
            ),
        ]

        fake_pack = MagicMock()
        fake_pack.slug = "default"
        fake_plan = MagicMock()
        fake_plan.metadata = {}
        fake_pack.project_planner = MagicMock(return_value=fake_plan)

        ps = self._patches(fake_port, fake_pack)
        with ps[0], ps[1], ps[2], ps[3]:
            plan_and_create_project(
                goal="draft Q3 stewardship project",
                plan_id="pid",
                project_title=None,
                user_id="u",
                workspace_id="ws-1",
            )

        fake_pack.project_planner.assert_called_once()
        kwargs = fake_pack.project_planner.call_args.kwargs
        retrieved = kwargs["extra_context"].get("retrieved_context")
        assert retrieved, (
            "plan_and_create_project must prefetch RAG chunks and pass "
            "them under extra_context.retrieved_context — mirrors the "
            "plan_and_run_with_llm grounding path."
        )
        assert retrieved[0]["content"].startswith("Sprouted Roots")

    def test_project_planner_runs_without_retrieved_context_when_index_empty(self):
        fake_port = MagicMock()
        fake_port.search.return_value = []

        fake_pack = MagicMock()
        fake_pack.slug = "default"
        fake_plan = MagicMock()
        fake_plan.metadata = {}
        fake_pack.project_planner = MagicMock(return_value=fake_plan)

        ps = self._patches(fake_port, fake_pack)
        with ps[0], ps[1], ps[2], ps[3]:
            plan_and_create_project(
                goal="draft Q3 stewardship project",
                plan_id="pid",
                project_title=None,
                user_id="u",
                workspace_id="ws-1",
            )

        kwargs = fake_pack.project_planner.call_args.kwargs
        # Empty retrieval — key should NOT be set, matching
        # plan_and_run_with_llm behaviour.  This is the "still build a
        # plan even when grounding is empty" contract.
        assert "retrieved_context" not in kwargs["extra_context"]


class TestPrefetchUsesQueryRewriter:
    """Tier 3 #9 — the prefetch path must rewrite the goal before
    searching, so short queries like ``"tldr"`` land closer to the
    snapshot chunks under cosine similarity.  See
    ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #9.
    """

    def test_prefetch_passes_rewritten_query_to_vector_store(self):
        fake_port = MagicMock()
        fake_port.search.return_value = []

        with patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ), patch(
            "components.knowledge.application.use_cases."
            "rewrite_query_for_retrieval_use_case."
            "RewriteQueryForRetrievalUseCase.rewrite",
            return_value="EXPANDED workspace mission summary",
        ):
            _prefetch_retrieved_context(workspace_id="ws-1", goal="tldr")

        # The vector store was searched with the rewritten query,
        # not the raw "tldr".
        fake_port.search.assert_called_once()
        kwargs = fake_port.search.call_args.kwargs
        assert kwargs["query"] == "EXPANDED workspace mission summary"
        assert kwargs["query"] != "tldr"

    def test_prefetch_swallows_rewriter_errors(self):
        """If the rewriter raises, the outer try/except in
        ``_prefetch_retrieved_context`` catches it and returns [] —
        the planner can still run without grounding."""
        fake_port = MagicMock()
        fake_port.search.return_value = []

        with patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ), patch(
            "components.knowledge.application.use_cases."
            "rewrite_query_for_retrieval_use_case."
            "RewriteQueryForRetrievalUseCase.rewrite",
            side_effect=RuntimeError("rewriter exploded"),
        ):
            result = _prefetch_retrieved_context(
                workspace_id="ws-1", goal="tldr"
            )

        assert result == []
