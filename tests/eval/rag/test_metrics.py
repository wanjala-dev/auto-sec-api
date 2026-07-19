"""Unit tests for the four RAG eval metrics.

These tests stay inside the metrics package — they verify the
deterministic surfaces (parsers, set arithmetic, edge cases) without
calling real LLMs. The judge LLM is replaced with `StubJudge` so the
test asserts what the metric does GIVEN a known judge response.

Integration tests (running the metrics against the live RAG pipeline)
live in the harness itself — see runner.py + the report it produces.
"""
from __future__ import annotations

import pytest

from tests.eval.rag.judge import JudgeRequest, StubJudge
from tests.eval.rag.metrics import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
    MetricResult,
)
from tests.eval.rag.metrics.answer_relevancy import _parse_rating
from tests.eval.rag.metrics.context_precision import _parse_verdict as _parse_cp_verdict
from tests.eval.rag.metrics.faithfulness import _parse_claims, _parse_verdict as _parse_f_verdict


# ── MetricResult invariants ───────────────────────────────────────────


class TestMetricResultValidation:
    def test_rejects_score_below_zero(self):
        with pytest.raises(ValueError):
            MetricResult(name="x", score=-0.1, detail={})

    def test_rejects_score_above_one(self):
        with pytest.raises(ValueError):
            MetricResult(name="x", score=1.5, detail={})

    def test_accepts_zero_and_one(self):
        MetricResult(name="x", score=0.0, detail={})
        MetricResult(name="x", score=1.0, detail={})


# ── ContextRecall (deterministic, no LLM) ─────────────────────────────


class TestContextRecall:
    def test_perfect_recall_when_all_expected_sections_retrieved(self):
        r = ContextRecall().score(
            prompt_id="t1",
            expected_sections=["members", "identity"],
            retrieved_chunks=[
                {"metadata": {"section": "members"}, "content": "..."},
                {"metadata": {"section": "identity"}, "content": "..."},
                {"metadata": {"section": "top_entities"}, "content": "..."},
            ],
        )
        assert r.score == 1.0
        assert set(r.detail["matched_sections"]) == {"members", "identity"}

    def test_partial_recall(self):
        r = ContextRecall().score(
            prompt_id="t1",
            expected_sections=["members", "identity", "team"],
            retrieved_chunks=[
                {"metadata": {"section": "members"}, "content": "..."},
            ],
        )
        # Only 1 of 3 expected sections retrieved → 1/3.
        assert r.score == pytest.approx(1 / 3)
        assert r.detail["missing_sections"] == ["identity", "team"]

    def test_empty_expected_sections_is_vacuously_perfect(self):
        """Multi-route prompts have no specific expected sections —
        the metric must not penalise them.
        """
        r = ContextRecall().score(
            prompt_id="t1",
            expected_sections=[],
            retrieved_chunks=[
                {"metadata": {"section": "top_entities"}, "content": "..."}
            ],
        )
        assert r.score == 1.0
        assert r.detail["reason"].startswith("empty expected_sections")

    def test_chunk_with_missing_section_metadata_is_classified_unknown(self):
        r = ContextRecall().score(
            prompt_id="t1",
            expected_sections=["unknown"],
            retrieved_chunks=[
                {"metadata": {}, "content": "..."},
            ],
        )
        # The chunk's section is reported as "unknown" and that
        # happens to match the expected — score 1.0. The point of
        # the test isn't the score; it's that the metric doesn't
        # crash on missing metadata.
        assert r.score == 1.0

    def test_detail_is_always_json_serializable(self):
        """Regression: the empty-expected branch was returning a raw
        ``set`` in detail which broke the score-phase JSON write.

        Caught 2026-06-10 during the first live baseline run.
        """
        import json

        for expected in ([], ["members"], ["members", "team"]):
            r = ContextRecall().score(
                prompt_id="t1",
                expected_sections=expected,
                retrieved_chunks=[
                    {"metadata": {"section": "members"}, "content": "..."},
                    {"metadata": {"section": "top_entities"}, "content": "..."},
                ],
            )
            # Must not raise — sets would crash here.
            json.dumps(r.detail)


# ── AnswerRelevancy ───────────────────────────────────────────────────


class TestAnswerRelevancy:
    def test_rating_5_maps_to_1(self):
        judge = StubJudge(lambda req: "RATING: 5\nREASON: directly answers")
        r = AnswerRelevancy().score(
            prompt_id="t1",
            question="What is Zaylan's mission?",
            answer="Zaylan is a literacy nonprofit.",
            judge=judge,
        )
        assert r.score == 1.0
        assert r.detail["rating"] == 5

    def test_rating_3_maps_to_0_5(self):
        judge = StubJudge(lambda req: "RATING: 3\nREASON: partial")
        r = AnswerRelevancy().score(
            prompt_id="t1",
            question="What is Zaylan's mission?",
            answer="Zaylan exists.",
            judge=judge,
        )
        assert r.score == 0.5

    def test_rating_1_maps_to_0(self):
        judge = StubJudge(lambda req: "RATING: 1\nREASON: off-topic")
        r = AnswerRelevancy().score(
            prompt_id="t1",
            question="What is Zaylan's mission?",
            answer="The weather is sunny.",
            judge=judge,
        )
        assert r.score == 0.0

    def test_empty_answer_short_circuits_to_zero_without_judge_call(self):
        called: list[JudgeRequest] = []

        def trap(req: JudgeRequest) -> str:
            called.append(req)
            return "RATING: 5\nREASON: x"

        r = AnswerRelevancy().score(
            prompt_id="t1",
            question="?",
            answer="",
            judge=StubJudge(trap),
        )
        assert r.score == 0.0
        assert called == [], "Empty answer must not trigger a judge call"

    def test_unparseable_judge_response_scores_zero(self):
        judge = StubJudge(lambda req: "This is not a rating.")
        r = AnswerRelevancy().score(
            prompt_id="t1",
            question="?",
            answer="x",
            judge=judge,
        )
        assert r.score == 0.0
        assert r.detail["reason"] == "unparseable judge response"

    def test_rating_out_of_range_is_unparseable(self):
        judge = StubJudge(lambda req: "RATING: 9\nREASON: x")
        r = AnswerRelevancy().score(
            prompt_id="t1",
            question="?",
            answer="x",
            judge=judge,
        )
        assert r.score == 0.0


class TestParseRating:
    def test_parses_simple_rating(self):
        assert _parse_rating("RATING: 4\nREASON: ok") == (4, "ok")

    def test_case_insensitive(self):
        assert _parse_rating("rating: 3\nreason: meh") == (3, "meh")

    def test_extra_whitespace_tolerated(self):
        assert _parse_rating("  RATING :   2\n  REASON :   poor  ") == (2, "poor")

    def test_returns_none_on_garbage(self):
        rating, _reason = _parse_rating("nope")
        assert rating is None

    def test_out_of_range_returns_none(self):
        for bad in ("0", "6", "10", "-1"):
            rating, _r = _parse_rating(f"RATING: {bad}\nREASON: x")
            assert rating is None, f"{bad} must be rejected"


# ── ContextPrecision ──────────────────────────────────────────────────


class TestContextPrecision:
    def test_all_chunks_relevant(self):
        judge = StubJudge(lambda req: "VERDICT: yes\nREASON: matches")
        r = ContextPrecision().score(
            prompt_id="t1",
            question="?",
            retrieved_chunks=[
                {"content": "a", "metadata": {"section": "members"}},
                {"content": "b", "metadata": {"section": "identity"}},
            ],
            judge=judge,
        )
        assert r.score == 1.0
        assert r.detail["relevant_chunks"] == 2
        assert r.detail["total_chunks"] == 2

    def test_half_chunks_relevant(self):
        responses = iter(["VERDICT: yes", "VERDICT: no"])
        judge = StubJudge(lambda req: next(responses))
        r = ContextPrecision().score(
            prompt_id="t1",
            question="?",
            retrieved_chunks=[
                {"content": "a", "metadata": {"section": "members"}},
                {"content": "b", "metadata": {"section": "top_entities"}},
            ],
            judge=judge,
        )
        assert r.score == 0.5

    def test_no_retrieved_chunks_scores_zero(self):
        r = ContextPrecision().score(
            prompt_id="t1",
            question="?",
            retrieved_chunks=[],
            judge=StubJudge(lambda _: "VERDICT: yes"),
        )
        assert r.score == 0.0
        assert r.detail["reason"] == "no retrieved chunks"

    def test_empty_content_chunk_counts_as_not_relevant(self):
        r = ContextPrecision().score(
            prompt_id="t1",
            question="?",
            retrieved_chunks=[{"content": "", "metadata": {"section": "members"}}],
            judge=StubJudge(lambda _: "VERDICT: yes"),
        )
        assert r.score == 0.0

    def test_unparseable_verdict_counts_as_not_relevant(self):
        judge = StubJudge(lambda req: "I'm sorry, I can't comply.")
        r = ContextPrecision().score(
            prompt_id="t1",
            question="?",
            retrieved_chunks=[{"content": "a", "metadata": {}}],
            judge=judge,
        )
        assert r.score == 0.0


class TestParseCpVerdict:
    def test_yes(self):
        assert _parse_cp_verdict("VERDICT: yes\nREASON: ok") == ("yes", "ok")

    def test_no(self):
        assert _parse_cp_verdict("verdict: NO\nreason: off") == ("no", "off")

    def test_unparseable_returns_none(self):
        v, _r = _parse_cp_verdict("hmm")
        assert v is None


# ── Faithfulness ──────────────────────────────────────────────────────


class TestFaithfulness:
    def test_all_claims_supported(self):
        responses = iter(
            [
                "CLAIM 1: Zaylan is a nonprofit\nCLAIM 2: It runs literacy programs",
                "VERDICT: supported\nREASON: in context",
                "VERDICT: supported\nREASON: in context",
            ]
        )
        judge = StubJudge(lambda req: next(responses))
        r = Faithfulness().score(
            prompt_id="t1",
            answer="Zaylan is a nonprofit. It runs literacy programs.",
            retrieved_chunks=[
                {"content": "Zaylan is a nonprofit running literacy programs.", "metadata": {}}
            ],
            judge=judge,
        )
        assert r.score == 1.0
        assert r.detail["supported_claims"] == 2
        assert r.detail["total_claims"] == 2

    def test_half_claims_supported(self):
        responses = iter(
            [
                "CLAIM 1: Zaylan is a nonprofit\nCLAIM 2: It has 500 staff",
                "VERDICT: supported\nREASON: in context",
                "VERDICT: unsupported\nREASON: 500 not stated",
            ]
        )
        judge = StubJudge(lambda req: next(responses))
        r = Faithfulness().score(
            prompt_id="t1",
            answer="Zaylan is a nonprofit. It has 500 staff.",
            retrieved_chunks=[{"content": "Zaylan is a nonprofit.", "metadata": {}}],
            judge=judge,
        )
        assert r.score == 0.5

    def test_no_claims_extracted_scores_zero(self):
        judge = StubJudge(lambda req: "NO_CLAIMS")
        r = Faithfulness().score(
            prompt_id="t1",
            answer="Hi!",
            retrieved_chunks=[{"content": "x", "metadata": {}}],
            judge=judge,
        )
        assert r.score == 0.0
        assert r.detail["reason"] == "no parseable claims extracted"

    def test_no_context_short_circuits_without_per_claim_calls(self):
        called: list[JudgeRequest] = []

        def trap(req: JudgeRequest) -> str:
            called.append(req)
            if "::extract" in req.prompt_id:
                return "CLAIM 1: x"
            return "VERDICT: supported"

        r = Faithfulness().score(
            prompt_id="t1",
            answer="x",
            retrieved_chunks=[],
            judge=StubJudge(trap),
        )
        assert r.score == 0.0
        # Only the extract call should have fired; per-claim judge
        # calls must short-circuit when context is empty.
        assert all("::extract" in c.prompt_id for c in called), (
            "When no context is supplied, per-claim judge calls must "
            "be skipped."
        )

    def test_empty_answer_short_circuits(self):
        called: list[JudgeRequest] = []
        judge = StubJudge(lambda req: called.append(req) or "CLAIM 1: x")
        r = Faithfulness().score(
            prompt_id="t1",
            answer="",
            retrieved_chunks=[{"content": "x", "metadata": {}}],
            judge=judge,
        )
        assert r.score == 0.0
        assert called == [], "Empty answer must not trigger judge calls"

    def test_tool_evidence_alone_is_enough_to_judge_claims(self):
        """Transactional category bug fix: when the snapshot chunks
        don't carry transaction figures but a tool call did,
        Faithfulness must score against the tool output."""
        seen_contexts: list[str] = []

        def trap(req: JudgeRequest) -> str:
            if "::extract" in req.prompt_id:
                return "CLAIM 1: Zaylan raised twelve thousand five hundred dollars"
            seen_contexts.append(req.user)
            return "VERDICT: supported\nREASON: in tool output"

        r = Faithfulness().score(
            prompt_id="t1",
            answer="Zaylan raised twelve thousand five hundred dollars.",
            retrieved_chunks=[],
            tool_evidence=[
                {
                    "agent_type": "DonationAgent",
                    "tool_name": "top_donors",
                    "tool_input": "{}",
                    "tool_output": "Total raised: $12,500 across 4 donors.",
                }
            ],
            judge=StubJudge(trap),
        )
        assert r.score == 1.0, (
            "Tool evidence must count as authoritative context — "
            "without this the transactional row scores 0 because "
            "the snapshot chunks don't carry dollar amounts."
        )
        # The judge prompt must have contained the tool output, with a
        # clear `[tool N agent=... name=...]` header so it reads as
        # authoritative material, not a third retrieved corpus to
        # be skeptical of.
        assert seen_contexts, "Per-claim judge call did not fire"
        ctx = seen_contexts[0]
        assert "Total raised: $12,500" in ctx
        assert "[tool 1" in ctx
        assert "agent=DonationAgent" in ctx
        assert "name=top_donors" in ctx

    def test_tool_evidence_appears_before_retrieved_chunks(self):
        """Tool observations are emitted first because they're the
        data the agent actively pulled; chunks are the ambient
        background it had retrieved."""

        def trap(req: JudgeRequest) -> str:
            if "::extract" in req.prompt_id:
                return "CLAIM 1: irrelevant"
            return "VERDICT: supported"

        r = Faithfulness().score(
            prompt_id="t1",
            answer="irrelevant",
            retrieved_chunks=[
                {
                    "content": "Zaylan is a nonprofit.",
                    "metadata": {"section": "identity"},
                }
            ],
            tool_evidence=[
                {
                    "agent_type": "FinancialAgent",
                    "tool_name": "summary",
                    "tool_input": "",
                    "tool_output": "Revenue YTD: $90K",
                }
            ],
            judge=StubJudge(trap),
        )
        # Walk into the metric internals to assert ordering — render
        # the context string the judge would have seen and confirm
        # the tool block precedes the chunk block.
        from tests.eval.rag.metrics.faithfulness import _format_context

        rendered = _format_context(
            [
                {
                    "content": "Zaylan is a nonprofit.",
                    "metadata": {"section": "identity"},
                }
            ],
            [
                {
                    "agent_type": "FinancialAgent",
                    "tool_name": "summary",
                    "tool_input": "",
                    "tool_output": "Revenue YTD: $90K",
                }
            ],
        )
        tool_pos = rendered.index("[tool 1")
        chunk_pos = rendered.index("[chunk 1")
        assert tool_pos < chunk_pos, (
            "Tool evidence must render before retrieved chunks so "
            "the judge reads it as ground truth the agent ran, not "
            "as a third corpus."
        )
        # And the metric itself still returns a valid result.
        assert r.score == 1.0

    def test_no_context_at_all_short_circuits(self):
        """When neither chunks nor tool evidence supply context,
        Faithfulness must not waste judge calls on per-claim
        verdicts — it should short-circuit with a clear reason."""
        called: list[JudgeRequest] = []

        def trap(req: JudgeRequest) -> str:
            called.append(req)
            return "CLAIM 1: x"

        r = Faithfulness().score(
            prompt_id="t1",
            answer="x",
            retrieved_chunks=[],
            tool_evidence=[],
            judge=StubJudge(trap),
        )
        assert r.score == 0.0
        assert "no retrieved context or tool evidence" in r.detail["reason"]
        # The extract call still fires (we don't know the claim
        # count until we ask); per-claim judge calls must not.
        assert all("::extract" in c.prompt_id for c in called)

    def test_truncated_flag_renders_in_tool_block_header(self):
        """If the production persist layer truncated a tool output,
        the rendered context must label the block ``truncated`` so a
        human reading the verdict detail knows the judge saw less
        than the full payload."""
        from tests.eval.rag.metrics.faithfulness import _format_context

        rendered = _format_context(
            [],
            [
                {
                    "agent_type": "DonationAgent",
                    "tool_name": "top_donors",
                    "tool_output": "Truncated CSV row 1\nRow 2",
                    "truncated_output": True,
                }
            ],
        )
        assert "truncated" in rendered
        assert "Truncated CSV row 1" in rendered

    def test_empty_tool_output_block_is_skipped(self):
        """A tool that returned the empty string shouldn't render a
        dangling header in the context block."""
        from tests.eval.rag.metrics.faithfulness import _format_context

        rendered = _format_context(
            [{"content": "real chunk", "metadata": {}}],
            [
                {
                    "agent_type": "X",
                    "tool_name": "noop",
                    "tool_output": "",
                }
            ],
        )
        assert "[tool 1" not in rendered, (
            "Tool blocks with empty output must be skipped, not "
            "rendered as a dangling header with no body."
        )
        assert "real chunk" in rendered


class TestParseClaims:
    def test_extracts_numbered_claims(self):
        assert _parse_claims("CLAIM 1: A is B\nCLAIM 2: C is D") == ["A is B", "C is D"]

    def test_returns_empty_on_no_claims_sentinel(self):
        assert _parse_claims("NO_CLAIMS") == []

    def test_returns_empty_on_garbage(self):
        assert _parse_claims("hello world") == []

    def test_strips_whitespace(self):
        assert _parse_claims("CLAIM 1:   spacey   ") == ["spacey"]


class TestParseFaithfulnessVerdict:
    def test_supported(self):
        assert _parse_f_verdict("VERDICT: supported\nREASON: yes") == (
            "supported",
            "yes",
        )

    def test_unsupported(self):
        assert _parse_f_verdict("VERDICT: unsupported\nREASON: no") == (
            "unsupported",
            "no",
        )

    def test_invalid_verdict_value_returns_none(self):
        v, _r = _parse_f_verdict("VERDICT: maybe")
        assert v is None
