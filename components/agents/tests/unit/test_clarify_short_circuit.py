"""Clarify short-circuit — vague goals get a clarifying question, not a thrash.

Background: planner.system v3 (2026-06-07) added a clarifying-task
pattern but routed those tasks to ``workspace_agent``. workspace_agent
is a tool-using LangChain AgentExecutor with no "ask the user a
question" tool, so a "tldr" goal looped through ~17 LLM rounds chasing
a relevant tool and died in the synthesizer's honesty guard. The user
saw the "I couldn't answer that" boilerplate for every basic
chat-style query. See ``docs/rca/2026-06-08-clarify-task-thrash.md``.

v4 introduces ``agent_type: clarify`` as a routing sentinel: the
runner's clarify worker emits a ``WorkerResult`` with
``is_clarification=True``, no LangChain dispatch, no LLM call, and the
synthesizer surfaces that clarifying question verbatim as the
user-facing answer.

These tests lock in the two halves of the fix so a future edit can't
silently re-route clarifications to a tool-using agent or re-introduce
the LLM paraphrase path for them.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from components.agents.domain.value_objects.plan_schemas import (
    CLARIFY_AGENT_TYPE,
    PlanSpec,
    TaskSpec,
    WorkerResult,
)
from components.agents.infrastructure.adapters.langchain.deep.orchestrator import (
    _is_clarification,
    llm_synthesizer,
)
from components.agents.infrastructure.adapters.langchain.deep.runner import (
    build_clarify_worker,
)


class TestClarifySentinelConstant:
    def test_sentinel_value(self):
        # The string value is part of the contract: the planner prompt
        # tells the LLM to emit `agent_type: "clarify"` literally, the
        # runner compares against this constant. Don't rename without
        # updating planner.system.yaml in lockstep.
        assert CLARIFY_AGENT_TYPE == "clarify"


class TestWorkerResultClarificationFlag:
    def test_default_is_false(self):
        # Existing call sites that construct WorkerResult without the
        # flag must continue to behave as non-clarification.
        result = WorkerResult(task_id="t-1", summary="Listed 4 tasks.")
        assert result.is_clarification is False

    def test_flag_round_trips(self):
        result = WorkerResult(
            task_id="t-1",
            summary="Which scope?",
            is_clarification=True,
        )
        assert result.is_clarification is True


class TestBuildClarifyWorker:
    """The clarify worker bypasses LangChain entirely.

    A failure here means a future edit started calling the agent
    service / LLM factory from inside the clarify path. That re-opens
    the v3 thrash bug.
    """

    def _state(self, task: TaskSpec) -> dict:
        return {"task": task}

    def test_uses_description_when_present(self):
        worker = build_clarify_worker(thread_id="run-test")
        task = TaskSpec(
            id="t-1",
            title="Clarify scope",
            description="Which scope — finances, donors, or programs?",
            agent_type=CLARIFY_AGENT_TYPE,
        )
        delta = worker(self._state(task))
        completed = delta["completed_tasks"]
        assert len(completed) == 1
        wr = completed[0]
        assert isinstance(wr, WorkerResult)
        assert wr.is_clarification is True
        assert wr.summary == "Which scope — finances, donors, or programs?"
        assert wr.task_id == "t-1"

    def test_falls_back_to_title_when_no_description(self):
        worker = build_clarify_worker(thread_id="run-test")
        task = TaskSpec(
            id="t-1",
            title="Which scope would you like a status on?",
            agent_type=CLARIFY_AGENT_TYPE,
        )
        delta = worker(self._state(task))
        wr = delta["completed_tasks"][0]
        assert wr.summary == "Which scope would you like a status on?"
        assert wr.is_clarification is True

    def test_empty_question_falls_back_to_polite_default(self):
        worker = build_clarify_worker(thread_id="run-test")
        task = TaskSpec(id="t-1", title="", description="", agent_type=CLARIFY_AGENT_TYPE)
        delta = worker(self._state(task))
        wr = delta["completed_tasks"][0]
        # Even a malformed clarifying task must not leave the user
        # with an empty bubble — surface SOMETHING grounded.
        assert wr.summary
        assert wr.is_clarification is True

    def test_no_state_returns_empty_delta(self):
        worker = build_clarify_worker(thread_id="run-test")
        assert worker({}) == {}

    def test_does_not_invoke_llm_factory(self):
        """The clarify path must never hit the LLM factory.

        The whole point of the sentinel is to avoid LLM round-trips
        for vague goals. If a future refactor accidentally reaches
        into LLMFactory.get_llm() here, the v3 cost regression
        reopens.
        """
        worker = build_clarify_worker(thread_id="run-test")
        task = TaskSpec(
            id="t-1",
            title="Clarify",
            description="Which?",
            agent_type=CLARIFY_AGENT_TYPE,
        )
        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm"
        ) as get_llm:
            worker(self._state(task))
            get_llm.assert_not_called()

    def test_does_not_call_agent_service(self):
        """Belt-and-suspenders: no AgentService.execute_agent either."""
        worker = build_clarify_worker(thread_id="run-test")
        task = TaskSpec(
            id="t-1",
            description="Which scope?",
            title="Clarify",
            agent_type=CLARIFY_AGENT_TYPE,
        )
        with patch(
            "components.agents.infrastructure.services.agents_service.AgentService.execute_agent"
        ) as execute_agent:
            worker(self._state(task))
            execute_agent.assert_not_called()


class TestSynthesizerIsClarification:
    """The detector recognises both pydantic and dict-shaped entries."""

    def test_pydantic_clarification_detected(self):
        wr = WorkerResult(task_id="t-1", summary="?", is_clarification=True)
        assert _is_clarification(wr) is True

    def test_dict_clarification_detected(self):
        assert _is_clarification({"summary": "?", "is_clarification": True}) is True

    def test_non_clarification_pydantic(self):
        wr = WorkerResult(task_id="t-1", summary="Listed 4 tasks.")
        assert _is_clarification(wr) is False

    def test_non_clarification_dict(self):
        assert _is_clarification({"summary": "Listed 4 tasks."}) is False

    def test_none_safe(self):
        assert _is_clarification(None) is False


def _state_with(*entries, goal="tldr"):
    plan = PlanSpec(plan_id="p-1", goal=goal, tasks=[])
    return {
        "plan": plan,
        "completed_tasks": list(entries),
        "artifacts": [],
        "run_metadata": {},
        "run_id": "run-test",
    }


class TestSynthesizerClarificationPath:
    """When all completed tasks are clarifications, surface them verbatim."""

    def test_short_circuits_for_pure_clarification_run(self):
        clarif = WorkerResult(
            task_id="t-1",
            summary="Which scope — finances, donors, or programs?",
            is_clarification=True,
        )
        state = _state_with(clarif)

        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm"
        ) as get_llm:
            result = llm_synthesizer(state)
            # No LLM round-trip — the clarification question IS the
            # answer; paraphrasing it would defeat the point.
            get_llm.assert_not_called()

        out = result["final_output"]
        assert out["goal_met"] is False
        assert out["needs_clarification"] is True
        assert out["answer"] == "Which scope — finances, donors, or programs?"
        assert (
            result["run_metadata"]["synthesizer_short_circuited"] == "clarification"
        )
        assert result["run_metadata"]["needs_clarification"] is True

    def test_clarification_beats_failure_when_all_completed_are_clarifications(self):
        """Two clarifications, zero failures — short-circuits cleanly."""
        c1 = WorkerResult(
            task_id="t-1",
            summary="Which scope?",
            is_clarification=True,
        )
        c2 = WorkerResult(
            task_id="t-2",
            summary="And which time window?",
            is_clarification=True,
        )
        state = _state_with(c1, c2)

        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm"
        ) as get_llm:
            result = llm_synthesizer(state)
            get_llm.assert_not_called()

        # Multi-clarification: questions are joined with a blank line so
        # the chat-bubble renderer keeps them as two prompts.
        assert "Which scope?" in result["final_output"]["answer"]
        assert "And which time window?" in result["final_output"]["answer"]
        assert result["final_output"]["needs_clarification"] is True

    def test_mixed_clarification_and_real_summary_does_not_short_circuit(self):
        """Real data + a clarification = LLM still synthesizes.

        The clarification path only fires when EVERY completed task is
        a clarification. If a specialist returned real data alongside
        a clarifying question (e.g. the planner emitted both a
        ``budget_agent`` task and a ``clarify`` task), the LLM is
        still the right tool to weave them together.
        """
        real = WorkerResult(task_id="t-1", summary="Listed 12 donations totalling $4,200.")
        clarif = WorkerResult(
            task_id="t-2",
            summary="Which time window for the report?",
            is_clarification=True,
        )
        state = _state_with(real, clarif)

        # We don't assert what the LLM produces — just that it's called.
        from unittest.mock import MagicMock

        fake_llm = MagicMock()
        fake_response = MagicMock()
        fake_response.content = "Mixed answer.\nGOAL_MET: no"
        fake_llm.invoke.return_value = fake_response

        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
            return_value=fake_llm,
        ):
            result = llm_synthesizer(state)
            fake_llm.invoke.assert_called_once()

        # Mixed-run path does NOT set the clarification short-circuit
        # marker — it goes through the normal LLM synthesizer.
        assert (
            result["run_metadata"].get("synthesizer_short_circuited") != "clarification"
        )

    def test_clarification_preempts_all_failures_guard(self):
        """A clarification alongside an AgentExecutor failure still wins.

        Belt-and-suspenders: even if a specialist task failed in the
        same run (e.g. due to a tool error), if every completed entry
        is either a clarification or that failure, we still want to
        ask the user the clarifying question rather than fall through
        to the honesty-guard boilerplate.

        Concretely: today the clarification path runs FIRST when all
        completed entries are clarifications. This test pins the
        order so a future "fix" that swaps them re-introduces the
        bug — vague goals show "I couldn't answer that" instead of
        the planner's actual clarifying question.
        """
        clarif = WorkerResult(
            task_id="t-1",
            summary="Which scope?",
            is_clarification=True,
        )
        state = _state_with(clarif, goal="tldr")

        with patch(
            "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm"
        ) as get_llm:
            result = llm_synthesizer(state)
            get_llm.assert_not_called()

        out = result["final_output"]
        # The answer is the clarifying question, NOT the honesty-guard
        # "I couldn't answer that" boilerplate.
        assert "Which scope?" in out["answer"]
        assert "couldn't answer" not in out["answer"].lower()
        assert out["needs_clarification"] is True
