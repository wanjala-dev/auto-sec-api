"""Synthesizer honesty guard.

The 2026-05-08 RCA found that ``llm_synthesizer`` was paraphrasing
AgentExecutor stop strings ("Agent stopped due to iteration or time
limit before reaching a final answer.") into plausible-sounding success
narratives. The user asked "list our top donors", got a fabricated
"Top Donors Report", and trusted it.

The fix is two-part:
1. If EVERY task came back as a known failure shape, do NOT call the
   LLM at all — return an honest "I couldn't answer that" message with
   ``goal_met=False``.
2. If a run is mixed (some real summaries, some failures), tag the
   failures in the LLM prompt with ``[FAILED — DID NOT PRODUCE DATA]``
   so the model can't accidentally absorb them into the narrative.

These tests lock in both halves of the guard.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from components.agents.domain.value_objects.plan_schemas import (
    PlanSpec,
    PlanState,
    TaskSpec,
)
from components.agents.infrastructure.adapters.langchain.deep.orchestrator import (
    _format_honest_failure_answer,
    _is_agent_failure_summary,
    llm_synthesizer,
)


class TestIsAgentFailureSummary:
    @pytest.mark.parametrize(
        "summary",
        [
            "Agent stopped due to iteration or time limit before reaching a final answer.",
            "Agent stopped due to iteration limit",
            "Agent stopped due to time limit",
            "Agent stopped due to max iterations",
            "Could not parse LLM output: blah",
            "Failed to invoke agent: timeout",
            "MAX ITERATIONS REACHED while processing",
        ],
    )
    def test_known_failure_shapes_match(self, summary):
        assert _is_agent_failure_summary(summary), (
            f"Expected {summary!r} to be classified as a failure shape "
            "so the synthesizer doesn't paraphrase it into success."
        )

    @pytest.mark.parametrize(
        "summary",
        [
            "You have 4 todo tasks: A, B, C, D",
            "Listed 12 donations totalling $4,200.",
            "",
            "The agent ran but produced an empty result set",
        ],
    )
    def test_real_summaries_do_not_match(self, summary):
        assert not _is_agent_failure_summary(summary)


class TestHonestFailureAnswer:
    def test_includes_goal_when_present(self):
        answer = _format_honest_failure_answer(
            "list our top donors", ["Agent stopped due to iteration limit"]
        )
        assert "list our top donors" in answer
        assert "couldn't" in answer.lower() or "can't" in answer.lower()
        # Must NOT promise an answer it didn't produce.
        assert "Top Donors Report" not in answer
        assert "Here are" not in answer

    def test_handles_missing_goal(self):
        answer = _format_honest_failure_answer(
            None, ["Agent stopped due to iteration limit"]
        )
        # Still returns something user-visible.
        assert answer
        assert "couldn't" in answer.lower() or "can't" in answer.lower()


def _build_state(summaries, *, goal="list our top donors"):
    """Construct a PlanState with task summaries for the synthesizer."""
    plan = PlanSpec(plan_id="p-1", goal=goal, tasks=[])
    completed = [
        {"task_id": f"t-{idx}", "summary": summary, "artifacts": []}
        for idx, summary in enumerate(summaries)
    ]
    return {
        "plan": plan,
        "completed_tasks": completed,
        "artifacts": [],
        "run_metadata": {},
        "run_id": "run-test",
    }


class TestSynthesizerHonestyGuard:
    def test_short_circuits_when_all_tasks_failed(self):
        """Every task = AgentExecutor stop string → no LLM call, honest failure."""
        state = _build_state(
            [
                "Agent stopped due to iteration or time limit before reaching a final answer.",
                "Agent stopped due to iteration limit",
            ]
        )
        # If the LLM is invoked even once, the test fails — the guard
        # MUST short-circuit before the LLMFactory.get_llm() call.
        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm"
        ) as get_llm:
            result = llm_synthesizer(state)
            get_llm.assert_not_called()

        out = result["final_output"]
        assert out["goal_met"] is False
        assert "couldn't" in out["answer"].lower() or "can't" in out["answer"].lower()
        assert (
            result["run_metadata"]["synthesizer_short_circuited"]
            == "all_tasks_failed"
        )
        # Must not invent the goal-shaped answer the user asked for.
        assert "Top Donors Report" not in out["answer"]

    def test_mixed_run_calls_llm_with_failure_caveat(self):
        """One real summary + one failure → LLM still runs, prompt tags failure."""
        state = _build_state(
            [
                "Listed 12 donations totalling $4,200.",
                "Agent stopped due to iteration or time limit before reaching a final answer.",
            ]
        )
        fake_llm = MagicMock()
        fake_response = MagicMock()
        fake_response.content = (
            "Here are 12 donations totalling $4,200. The donor list "
            "wasn't available.\nGOAL_MET: no\nREPLAN_REQUESTED: yes"
        )
        fake_llm.invoke.return_value = fake_response

        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
            return_value=fake_llm,
        ):
            result = llm_synthesizer(state)

        # The LLM was called — and the prompt MUST contain both the
        # tagged failure and the explicit caveat. Otherwise the model
        # could paraphrase the failure as success.
        prompt_call = fake_llm.invoke.call_args.args[0]
        prompt_text = "\n".join(getattr(m, "content", "") for m in prompt_call)
        assert "[FAILED — DID NOT PRODUCE DATA]" in prompt_text
        assert "Do NOT invent results" in prompt_text
        # Real summaries pass through untagged.
        assert "Listed 12 donations totalling $4,200." in prompt_text

        # Output is whatever the LLM returned, with goal_met=False.
        assert result["final_output"]["goal_met"] is False
        assert result["run_metadata"].get("replan_requested") is True

    def test_all_real_summaries_do_not_get_tagged(self):
        """No failures → no caveat, no tags. Don't poison happy-path prompts."""
        state = _build_state(
            [
                "Listed 12 donations.",
                "Found 4 todo tasks.",
            ]
        )
        fake_llm = MagicMock()
        fake_response = MagicMock()
        fake_response.content = "All good.\nGOAL_MET: yes"
        fake_llm.invoke.return_value = fake_response

        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
            return_value=fake_llm,
        ):
            llm_synthesizer(state)

        prompt_call = fake_llm.invoke.call_args.args[0]
        prompt_text = "\n".join(getattr(m, "content", "") for m in prompt_call)
        assert "[FAILED — DID NOT PRODUCE DATA]" not in prompt_text
        assert "Do NOT invent results" not in prompt_text
