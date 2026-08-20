"""The rubric stamp must survive the trip from writer to reader.

ADR 0032 D12 / §1.3.2. Both halves of this loop were tested in isolation and
both halves passed. The writer's tests asserted it stamps
``{"verdict": "satisfied"}``; the reader's tests fed it hand-built dicts in the
shape the reader expected (``{"satisfied": True}``) — a shape the writer has
never produced. The result: ``rubric_pass_count`` was **0 for every run ever
graded**, ``rubric_fail_count`` counted every graded answer as a failure, and
nothing anywhere was red.

So this file deliberately does NOT hand-build a stamp. It runs the real
``summarize_rubric_evaluations`` over real evaluation dicts and hands its
output — untouched — to the real ``_eval_fields``. Any future divergence
between the two sides fails here, which is the only place it can be seen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from components.agents.domain.value_objects.rubric_verdict import (
    RUBRIC_VERDICT_MAX_ITERATIONS_REACHED,
    RUBRIC_VERDICT_SATISFIED,
)
from components.agents.infrastructure.adapters.langchain.deep.rubric import (
    summarize_rubric_evaluations,
)
from components.agents.infrastructure.repositories.orm_deep_run_query_repository import (
    _eval_fields,
)

pytestmark = pytest.mark.unit


class _Run:
    """The two timestamps ``_eval_fields`` reads off the ORM row."""

    def __init__(self) -> None:
        self.created_at = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        self.updated_at = self.created_at + timedelta(seconds=3)


def _evaluation(result: str, *, run_id: str = "grading-1", explanation: str = "ok"):
    """One ``RubricEvaluation`` as deepagents actually delivers it: a dict."""
    return {
        "grading_run_id": run_id,
        "iteration": 1,
        "result": result,
        "explanation": explanation,
        "criteria": [],
    }


def _stats_for(*results: str) -> dict:
    """Write a stamp the real way, then read it the real way."""
    stamp = summarize_rubric_evaluations(
        [_evaluation(r) for r in results],
        max_iterations=2,
        grader_model="gpt-4o-mini",
    )
    state = {"run_metadata": {"rubric_verdicts": {"task-1": stamp}}}
    return _eval_fields(state, _Run())


class TestVerdictRoundTrip:
    def test_a_satisfied_answer_counts_as_a_pass(self):
        """The whole bug, in one assertion: this used to be 0."""
        stats = _stats_for(RUBRIC_VERDICT_SATISFIED)
        assert stats["rubric_pass_count"] == 1
        assert stats["rubric_fail_count"] == 0

    def test_a_failed_answer_counts_as_a_fail(self):
        stats = _stats_for("failed")
        assert stats["rubric_pass_count"] == 0
        assert stats["rubric_fail_count"] == 1

    def test_an_exhausted_revision_budget_is_a_fail_not_a_pass(self):
        """``needs_revision`` at the cap is derived to ``max_iterations_reached``."""
        stamp = summarize_rubric_evaluations(
            [_evaluation("needs_revision"), _evaluation("needs_revision")],
            max_iterations=2,
            grader_model="gpt-4o-mini",
        )
        assert stamp["verdict"] == RUBRIC_VERDICT_MAX_ITERATIONS_REACHED
        stats = _eval_fields({"run_metadata": {"rubric_verdicts": {"t": stamp}}}, _Run())
        assert stats["rubric_pass_count"] == 0
        assert stats["rubric_fail_count"] == 1

    def test_the_writers_key_is_the_one_the_reader_looks_for(self):
        """Named explicitly so a rename on either side fails HERE, loudly."""
        stamp = summarize_rubric_evaluations(
            [_evaluation(RUBRIC_VERDICT_SATISFIED)],
            max_iterations=2,
            grader_model="gpt-4o-mini",
        )
        assert "verdict" in stamp
        assert stamp["verdict"] == RUBRIC_VERDICT_SATISFIED


class TestAbsenceIsNotFailure:
    """ADR 0032 D4 — 'not graded' is a third state, never a failure."""

    def test_an_ungraded_run_reports_neither_pass_nor_fail(self):
        stats = _eval_fields({"run_metadata": {}}, _Run())
        assert stats["rubric_pass_count"] == 0
        assert stats["rubric_fail_count"] == 0

    def test_a_stamp_with_no_verdict_string_is_not_counted_as_a_fail(self):
        """A grader crash must not read as 'the agent failed'."""
        state = {"run_metadata": {"rubric_verdicts": {"t": {"iterations": 1, "feedback": ""}}}}
        stats = _eval_fields(state, _Run())
        assert stats["rubric_pass_count"] == 0
        assert stats["rubric_fail_count"] == 0

    def test_mixed_verdicts_sum_to_the_graded_count_only(self):
        stamps = {
            "a": summarize_rubric_evaluations(
                [_evaluation(RUBRIC_VERDICT_SATISFIED)], max_iterations=2, grader_model="g"
            ),
            "b": summarize_rubric_evaluations([_evaluation("failed")], max_iterations=2, grader_model="g"),
            "c": {"iterations": 0},  # never graded
        }
        stats = _eval_fields({"run_metadata": {"rubric_verdicts": stamps}}, _Run())
        assert stats["rubric_pass_count"] == 1
        assert stats["rubric_fail_count"] == 1
        assert stats["rubric_pass_count"] + stats["rubric_fail_count"] == 2
