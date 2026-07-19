"""The planner must retry once with a stricter prompt on empty plans.

``llm_planner.plan_with_llm`` (lines 293-306) re-calls the LLM with a
"REMINDER" prefix when the first response yields zero tasks. This is
the safety net that prevents a single LLM hiccup from leaving the user
with no agent action at all.

Until now this code path was untested. Without coverage, a refactor
could silently drop the retry and we'd start dropping user requests
on transient empty responses.
"""
from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep import llm_planner
from components.agents.tests._helpers.routing_mock_llm import SequencedMockLLM


def _patch_planner_llm(monkeypatch, mock_llm) -> None:
    monkeypatch.setattr(
        "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
        lambda **_: mock_llm,
    )


def test_planner_retries_when_first_response_has_no_tasks(monkeypatch):
    """First call returns ``{"tasks": []}``; second call returns valid.

    The planner must invoke the LLM twice and the final plan must
    contain the second response's task.
    """
    mock = SequencedMockLLM(
        contents=[
            '{"tasks": []}',  # first call: empty — triggers retry
            (
                '{"tasks": [{"title": "retry succeeded", '
                '"priority": "medium", "status": "todo", '
                '"agent_type": "task_agent"}]}'
            ),
        ]
    )
    _patch_planner_llm(monkeypatch, mock)

    plan = llm_planner.plan_with_llm(
        goal="vague goal that the first LLM call ignores",
        plan_id="t-retry-1",
        workspace_id="ws-test",
    )

    assert len(mock.invocations) == 2, (
        f"Planner invoked LLM {len(mock.invocations)} times — expected 2 "
        "(first call empty, second call after retry). The retry path is "
        "load-bearing for transient LLM hiccups."
    )

    assert plan.tasks, "Plan empty after retry — second response was lost."
    assert plan.tasks[0].title == "retry succeeded"
    assert plan.tasks[0].agent_type == "task_agent"


def test_retry_prompt_contains_reminder_keyword(monkeypatch):
    """The retry's stricter prompt must contain the word 'REMINDER'.

    Pinning the keyword lets us catch refactors that drop the stricter
    prompt entirely (in which case retries would be no-ops with the
    same prompt that failed once).
    """
    mock = SequencedMockLLM(
        contents=[
            '{"tasks": []}',
            (
                '{"tasks": [{"title": "second try", '
                '"priority": "medium", "status": "todo", '
                '"agent_type": "workspace_agent"}]}'
            ),
        ]
    )
    _patch_planner_llm(monkeypatch, mock)

    llm_planner.plan_with_llm(
        goal="something",
        plan_id="t-retry-2",
        workspace_id="ws-test",
    )

    # First call's messages — no REMINDER (or a baseline mention is OK,
    # we mainly assert the SECOND call has more text than the first).
    first_call_text = "\n".join(
        getattr(m, "content", "")
        for m in mock.invocations[0]
        if hasattr(m, "content")
    )
    second_call_text = "\n".join(
        getattr(m, "content", "")
        for m in mock.invocations[1]
        if hasattr(m, "content")
    )

    assert "REMINDER" in second_call_text, (
        "Retry prompt must include 'REMINDER' to nudge the LLM into "
        "outputting valid JSON with tasks. Without the stricter prompt, "
        "the retry is a coin flip — same prompt, same failure mode."
    )
    assert "REMINDER" not in first_call_text, (
        "First call's prompt should NOT contain the retry-specific "
        "REMINDER text — that's reserved for the retry path. If it "
        "leaks into the first call, the prompt is permanently in "
        "'panic mode' and probably degraded."
    )


def test_planner_does_not_retry_when_first_response_succeeds(monkeypatch):
    """Single LLM call when the first response has tasks — no wasted retry."""
    mock = SequencedMockLLM(
        contents=[
            (
                '{"tasks": [{"title": "first try worked", '
                '"priority": "medium", "status": "todo", '
                '"agent_type": "workspace_agent"}]}'
            ),
        ]
    )
    _patch_planner_llm(monkeypatch, mock)

    plan = llm_planner.plan_with_llm(
        goal="something",
        plan_id="t-retry-3",
        workspace_id="ws-test",
    )

    assert len(mock.invocations) == 1, (
        f"Planner invoked LLM {len(mock.invocations)} times — expected 1 "
        "(no retry needed when first response is valid). Burning extra "
        "LLM calls on success doubles cost for nothing."
    )
    assert plan.tasks
    assert plan.tasks[0].title == "first try worked"
