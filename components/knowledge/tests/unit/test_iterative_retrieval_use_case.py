"""Tier 3 #12 — unit tests for self-verification + retry loop.

The LLM port is stubbed; we verify the orchestration:

* Round 1 sufficient → return immediately (no rewriter call).
* Round 1 insufficient → reformulates and re-searches.
* Three rounds all insufficient → returns best round's chunks.
* Empty initial retrieval → sufficiency=0 → reformulates.
* Sufficiency scorer error → treats round as insufficient.
* Reformulator error → stops the loop, returns best so far.
* ``_parse_sufficiency_score`` — defensive parse of LLM responses.
* ``is_self_verify_enabled`` — env-var truthiness.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #12.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from components.knowledge.application.ports.llm_port import LlmResponse
from components.knowledge.application.ports.vector_store_port import RetrievedChunk
from components.knowledge.application.use_cases.iterative_retrieval_use_case import (
    DEFAULT_MAX_ROUNDS,
    SUFFICIENCY_THRESHOLD,
    IterativeRetrievalUseCase,
    _parse_sufficiency_score,
    is_self_verify_enabled,
)


def _c(text: str) -> RetrievedChunk:
    return RetrievedChunk(content=text, metadata={}, score=0.5)


def _llm_stub(responses):
    """Return a fake LlmPort that yields each response in order from chat()."""
    fake = MagicMock()
    fake.chat.side_effect = [LlmResponse(content=r) for r in responses]
    return fake


def _patch_llm(fake):
    return patch(
        "components.knowledge.application.providers."
        "ai_llm_provider.AILlmProvider.get_default_port",
        return_value=fake,
    )


class TestEnvVarToggle:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("KNOWLEDGE_SELF_VERIFY_ENABLED", raising=False)
        assert is_self_verify_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes", "YES"])
    def test_enabled_for_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("KNOWLEDGE_SELF_VERIFY_ENABLED", value)
        assert is_self_verify_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
    def test_disabled_for_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv("KNOWLEDGE_SELF_VERIFY_ENABLED", value)
        assert is_self_verify_enabled() is False


class TestParseSufficiencyScore:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("7", 7),
            ("10", 10),
            ("1", 1),
            ("8.", 8),
            ("Score: 9", 9),
            (" 6 ", 6),
            ("", 0),
            ("not a number", 0),
            # Clamp to 0-10 range.
            ("11", 10),
            ("0", 0),
        ],
    )
    def test_handles_various_response_shapes(self, text, expected):
        assert _parse_sufficiency_score(text) == expected


class TestIterativeLoop:
    def test_round_1_sufficient_returns_immediately(self):
        chunks = [_c("good chunk")]
        retriever = MagicMock(return_value=chunks)
        # LLM is asked exactly once — the sufficiency score.
        fake = _llm_stub(["9"])
        with _patch_llm(fake):
            result = IterativeRetrievalUseCase().retrieve(
                workspace_id="ws-1", goal="my goal", retriever=retriever
            )

        assert result == chunks
        assert fake.chat.call_count == 1
        retriever.assert_called_once_with(workspace_id="ws-1", query="my goal")

    def test_round_1_insufficient_reformulates_and_retries(self):
        round_1 = [_c("first try")]
        round_2 = [_c("better")]
        retriever = MagicMock(side_effect=[round_1, round_2])

        # Conversation: score=3 (insufficient) → reformulate → score=8 (done).
        fake = _llm_stub(["3", "new query", "8"])
        with _patch_llm(fake):
            result = IterativeRetrievalUseCase().retrieve(
                workspace_id="ws-1", goal="goal", retriever=retriever
            )

        assert result == round_2
        # Two searches: original goal + new query from rewriter.
        assert retriever.call_count == 2
        assert retriever.call_args_list[0].kwargs["query"] == "goal"
        assert retriever.call_args_list[1].kwargs["query"] == "new query"

    def test_max_rounds_returns_best_round_chunks(self):
        # All three rounds insufficient → return the highest-scoring.
        rounds = [[_c("r1")], [_c("r2")], [_c("r3")]]
        retriever = MagicMock(side_effect=rounds)
        fake = _llm_stub(
            [
                "2", "rewrite-a",  # round 1 → insufficient, reformulate
                "5", "rewrite-b",  # round 2 → insufficient, reformulate
                "4",                # round 3 → insufficient (last round, no rewrite)
            ]
        )
        with _patch_llm(fake):
            result = IterativeRetrievalUseCase(
                max_rounds=DEFAULT_MAX_ROUNDS
            ).retrieve(
                workspace_id="ws-1", goal="goal", retriever=retriever
            )

        # Best round is round 2 (score 5).
        assert result == [_c("r2")]
        assert retriever.call_count == 3

    def test_empty_initial_chunks_counts_as_zero_sufficiency(self):
        retriever = MagicMock(side_effect=[[], [_c("after rewrite")]])
        # round 1 chunks empty → scorer short-circuits to 0 (no LLM
        # call for that scoring round); then rewriter; then round 2
        # sufficiency = 9.
        fake = _llm_stub(["different query", "9"])
        with _patch_llm(fake):
            result = IterativeRetrievalUseCase().retrieve(
                workspace_id="ws-1", goal="goal", retriever=retriever
            )

        assert result == [_c("after rewrite")]

    def test_reformulator_failure_stops_loop_and_returns_best_so_far(self):
        round_1 = [_c("only round")]
        retriever = MagicMock(return_value=round_1)
        # Score 3 → reformulator raises → loop stops, return round_1.
        fake = MagicMock()
        fake.chat.side_effect = [
            LlmResponse(content="3"),
            RuntimeError("rewriter exploded"),
        ]
        with _patch_llm(fake):
            result = IterativeRetrievalUseCase().retrieve(
                workspace_id="ws-1", goal="goal", retriever=retriever
            )

        # We never got a second round, so the best (and only) result
        # is round_1.
        assert result == round_1
        assert retriever.call_count == 1

    def test_reformulator_returns_same_query_stops_loop(self):
        """If the rewriter can't think of anything new, abort the
        loop — re-running the same search would be pointless."""
        round_1 = [_c("only round")]
        retriever = MagicMock(return_value=round_1)
        # Insufficient + rewriter returns the same query → stop.
        fake = _llm_stub(["3", "goal"])  # "goal" matches the original
        with _patch_llm(fake):
            result = IterativeRetrievalUseCase().retrieve(
                workspace_id="ws-1", goal="goal", retriever=retriever
            )

        assert result == round_1
        assert retriever.call_count == 1

    def test_inner_search_failure_treats_round_as_empty(self):
        round_1_fail = RuntimeError("DB down")
        round_2 = [_c("recovered")]
        # First retriever call raises, but we should still proceed
        # to score=0 → reformulate → search again.
        retriever = MagicMock(side_effect=[round_1_fail, round_2])
        fake = _llm_stub(["different query", "9"])
        with _patch_llm(fake):
            result = IterativeRetrievalUseCase().retrieve(
                workspace_id="ws-1", goal="goal", retriever=retriever
            )

        assert result == round_2


class TestConstants:
    def test_default_max_rounds_is_three(self):
        # Per the roadmap.
        assert DEFAULT_MAX_ROUNDS == 3

    def test_sufficiency_threshold_is_seven(self):
        # 7-10 on the 1-10 scale stops the loop.
        assert SUFFICIENCY_THRESHOLD == 7
