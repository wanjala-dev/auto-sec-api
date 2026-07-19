"""Pattern B — planner routing execution test.

The 2026-05-08 cascade was caused by the planner LLM picking the wrong
``agent_type`` for "assign those tasks to me" (got ``workspace_agent``,
should have been ``task_agent``). At the time, our routing tests only
asserted the system prompt's *content* — not what the planner actually
did with it.

This file closes that gap. For every routing keyword in
``ROUTING_EXPECTATIONS``, we:

1. Mock ``LLMFactory.get_llm`` to return a ``RoutingMockLLM`` that
   maps goal substrings → ``agent_type``.
2. Call ``plan_with_llm(goal=...)`` with that goal.
3. Assert the returned ``plan.tasks[0].agent_type`` matches expectation.

This is deterministic and zero-LLM-cost. The mock doesn't simulate the
real LLM — it simulates "what the LLM SHOULD return given the routing
table in the prompt". The test's job is to confirm the planner threads
the goal through correctly and respects the ``agent_type`` field on the
returned JSON.

Pair this with ``test_planner_agent_routing.py`` (which asserts the
prompt CONTENT) — together they cover both halves of the contract:
the prompt tells the LLM the right thing, AND the planner respects
what the LLM returns.
"""
from __future__ import annotations

from typing import Dict

import pytest

from components.agents.infrastructure.adapters.langchain.deep import llm_planner
from components.agents.tests._helpers.agent_capability_inventory import (
    ROUTING_EXPECTATIONS,
)
from components.agents.tests._helpers.routing_mock_llm import RoutingMockLLM


def _patch_planner_llm(monkeypatch, mock_llm) -> None:
    """Patch the LLM factory the planner imports lazily.

    ``llm_planner.plan_with_llm`` does ``from components.knowledge…
    import LLMFactory`` inside the function, so monkey-patching
    ``llm_planner.LLMFactory`` doesn't reach it. Patch at the source.
    """
    monkeypatch.setattr(
        "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
        lambda **_: mock_llm,
    )


@pytest.mark.parametrize(
    ("goal", "expected_agent"),
    sorted(ROUTING_EXPECTATIONS.items()),
)
def test_planner_routes_goal_to_expected_agent(monkeypatch, goal, expected_agent):
    """Every entry in ``ROUTING_EXPECTATIONS`` must round-trip through the planner.

    If a goal/agent pair is added here, the routing rule that supports
    it must already be in the planner's system prompt — otherwise the
    real LLM would never emit the corresponding ``agent_type`` and this
    test (which mocks the LLM with the rules pre-baked) would mask a
    real production gap.
    """
    mock = RoutingMockLLM(routes=ROUTING_EXPECTATIONS)
    _patch_planner_llm(monkeypatch, mock)

    plan = llm_planner.plan_with_llm(
        goal=goal,
        plan_id="test-plan",
        workspace_id="ws-test",
    )

    assert len(plan.tasks) >= 1, (
        f"Planner produced an empty plan for goal {goal!r}. "
        "It must always emit at least one task — even chat-style goals "
        "should produce a single 'answer the user' task."
    )
    task = plan.tasks[0]
    assert task.agent_type == expected_agent, (
        f"Goal {goal!r} routed to {task.agent_type!r} but expected "
        f"{expected_agent!r}. The planner respected the LLM's choice — "
        "if this fails, either ROUTING_EXPECTATIONS is wrong or the "
        "RoutingMockLLM matching logic regressed."
    )


def test_planner_falls_back_to_workspace_agent_when_no_route_matches(monkeypatch):
    """Unknown goals must default to workspace_agent, NEVER fabricate a name.

    The planner system prompt explicitly says: 'If you cannot match the
    task to any specialist with confidence, default to ``workspace_agent``.
    Do NOT invent agent names.' Verify the planner respects that when
    the LLM emits the default.
    """
    mock = RoutingMockLLM(routes={}, default="workspace_agent")
    _patch_planner_llm(monkeypatch, mock)

    plan = llm_planner.plan_with_llm(
        goal="say hello",
        plan_id="test-plan",
        workspace_id="ws-test",
    )

    assert plan.tasks
    assert plan.tasks[0].agent_type == "workspace_agent"


def test_planner_passes_goal_through_to_llm_user_message(monkeypatch):
    """The user message the LLM sees must contain the literal goal.

    Catches future regressions where the planner accidentally drops the
    goal during prompt assembly (e.g. keying the JSON wrong).
    """
    mock = RoutingMockLLM(routes={"how many tasks": "task_agent"})
    _patch_planner_llm(monkeypatch, mock)

    llm_planner.plan_with_llm(
        goal="how many tasks do we have?",
        plan_id="test-plan",
        workspace_id="ws-test",
    )

    assert mock.invocations, "Planner did not invoke the LLM."
    last = mock.invocations[-1]
    assert last["goal"] == "how many tasks do we have?", (
        "Planner did not pass the goal through correctly. "
        f"Got: {last['goal']!r}"
    )
    assert last["chosen"] == "task_agent"


def test_routing_expectations_cover_every_canonical_specialist():
    """Every specialist in ``CANONICAL_TOOLS`` must have at least one
    routing keyword in ``ROUTING_EXPECTATIONS``. Otherwise we'd ship
    a specialist with zero routing-execution coverage.
    """
    from components.agents.tests._helpers.agent_capability_inventory import (
        CANONICAL_TOOLS,
    )

    routed_agents = set(ROUTING_EXPECTATIONS.values())
    expected_agents = set(CANONICAL_TOOLS.keys())

    missing = expected_agents - routed_agents
    assert not missing, (
        f"These specialists have no routing keyword in ROUTING_EXPECTATIONS: "
        f"{sorted(missing)}. Add at least one (goal, agent) pair so the "
        "routing-execution test exercises every agent."
    )
