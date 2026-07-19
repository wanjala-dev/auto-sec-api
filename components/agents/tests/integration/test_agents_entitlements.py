"""Entitlement enforcement for the deep-agent worker pipeline.

The legacy ReAct OrchestratorAgent has been retired. Entitlements used
to be enforced by filtering its sub-agent ReAct tools at construction
time. The deep pipeline enforces them at the worker boundary instead:
`build_worker_from_agent` rejects any agent_type not present in the
run's `allowed_agents` list before the worker ever runs.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep.adapters import (
    build_worker_from_agent,
)


def test_worker_blocked_when_not_in_allowed_agents():
    # `build_worker_from_agent` raises immediately at construction time
    # when the requested agent_type is not in the allow-list, so the
    # disallowed agent never reaches `AgentService.execute_agent`.
    with pytest.raises(PermissionError):
        build_worker_from_agent(
            agent_type="budget_agent",
            user_id="user-1",
            workspace_id="ws-1",
            run_context={
                "run_id": "run-1",
                "allowed_agents": ["task_agent", "donation_agent"],
            },
        )


def test_worker_allowed_when_in_allowed_agents():
    # We don't actually invoke the agent service here — the contract is
    # that build_worker_from_agent does NOT raise on construction when
    # the agent is in the allow-list. Calling worker() with no task
    # short-circuits before any service call.
    worker = build_worker_from_agent(
        agent_type="task_agent",
        user_id="user-1",
        workspace_id="ws-1",
        run_context={
            "run_id": "run-1",
            "allowed_agents": ["task_agent"],
        },
    )
    assert worker({}) == {}


def test_worker_allowed_when_no_allow_list():
    """An empty/None allow-list means everything is permitted."""
    worker = build_worker_from_agent(
        agent_type="sponsorship_agent",
        user_id="user-1",
        workspace_id="ws-1",
        run_context={"run_id": "run-1"},
    )
    assert worker({}) == {}
