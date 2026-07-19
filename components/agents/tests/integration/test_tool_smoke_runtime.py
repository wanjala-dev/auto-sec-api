"""Pattern E — every registered tool must execute without leaking
Python error markers when called with empty input.

Pattern C (per-agent inventory) and Pattern D (cross-agent overlap)
catch *registration* drift. They don't catch *implementation* drift —
the kind that broke ``project_agent.update_project_status`` (referenced
``project.notes`` / ``project.progress_percentage`` / ``project.updated_at``,
none of which exist on the Project model) and ``add_project_risk`` /
``get_project_risks`` (imported a ``Risk`` model that doesn't exist
anywhere in the codebase).

Pattern E closes that gap. For every (agent, tool) pair:

1. Spin up the agent against a real workspace + user + team fixture
   (so workspace-scoped lookups succeed).
2. Call ``tool.func("{}")`` — the minimal valid input every tool
   should accept (either passes, or returns a graceful "X is required"
   string).
3. Assert the response is a string AND contains no Python traceback
   markers (``AttributeError``, ``ImportError``, ``object has no
   attribute``, ``Field 'id' expected``, etc.).

Failure modes Pattern E catches that C/D miss:

- Drift between tool implementation and the actual model fields.
- Lazy imports of models that no longer exist.
- Type mismatches (e.g. tool passes UUID where model expects int).
- Helper functions that crash on empty input instead of returning
  a friendly error string.

What Pattern E does NOT catch:

- Logic bugs (tool runs cleanly but returns wrong answer).
- Tool-selection gaps (LLM picks the wrong tool — that's Pattern B).
- Permission bugs that only fire for non-admin users.
"""
from __future__ import annotations

import re
import uuid
from typing import Iterable, List, Tuple
from unittest.mock import MagicMock, patch

import pytest

from components.agents.infrastructure.adapters.langchain.base import AgentRegistry
from components.agents.tests._helpers.agent_capability_inventory import (
    CANONICAL_TOOLS,
    UNIVERSAL_TOOLS,
)


# Markers that almost certainly indicate a Python traceback or schema
# drift bubbled up to the LLM. Some of these phrases appear in
# legitimate response strings (e.g. "expected" in a UX message), so
# we anchor on the patterns that ONLY appear in tracebacks.
_TRACEBACK_MARKERS: Tuple[str, ...] = (
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "TypeError:",
    "object has no attribute",
    "expected a number but got",
    "is not a valid UUID",
    "FieldError",
    "Cannot resolve keyword",
    "got unexpected keyword arguments",
    "missing 1 required positional argument",
    "Manager isn't accessible via",
    "_meta.get_field",
)


# Tools that legitimately need to talk to a payment provider, an LLM,
# or other heavy external integrations. They will fail-fast on a smoke
# call without those dependencies — that's expected and not a drift bug.
# Skip them in the smoke harness.
_SMOKE_SKIP: dict[str, set[str]] = {
    # AI-heavy: calls the LLM internally to generate text/JSON.
    "fundraising_agent": {"generate_fundraising_plan"},
    "project_agent": {
        "create_project_from_prompt",
        "create_project_with_plan",
        "estimate_project_items",
    },
    "task_agent": {
        # Calls the LLM to break a task into subtasks.
        "break_down_task",
    },
    # Heavy generation pipeline: AI gateway + PDF render + notifications.
    # generate_financial_report does default-date validation (PR-G fix)
    # which makes it smoke-safe — but the actual generation step still
    # needs the AI gateway, so we keep it skipped here.
    "financial_agent": {"generate_financial_report"},
    # PR-H2 — sponsorship + donation report tools wrap the same heavy
    # FinancialReport generation pipeline. Same gateway dependency,
    # same skip rationale. The headline-numbers code path is exercised
    # by the per-tool integration tests in test_agent_chat_artifacts;
    # smoke-time empty-input call would still hit the provider.
    "sponsorship_agent": {"generate_sponsorship_report"},
    "donation_agent": {"generate_donation_report"},
    # 2026-05-09 — workspace_agent.generate_organization_report now
    # produces a PDF via the same FinancialReport pipeline (was text-
    # only before). Same AI-gateway skip rationale as the others.
    "workspace_agent": {"generate_organization_report"},
    # LLM-internal: build a JSON post draft via an internal LLM call
    # (the smoke fixture's MagicMock LLM provider can't satisfy this).
    "blog_agent": {"draft_social_post", "queue_social_post_task"},
}


# ── Known drift Pattern E surfaced ──
#
# Empty as of PR-G (2026-05-09): all 24 documented drift items are
# fixed; the 2 LLM-internal blog tools moved to ``_SMOKE_SKIP``.
#
# Future entries land here ``strict=True`` xfailed when a specific
# tool needs a follow-up fix. Once the fix lands, the entry is
# removed and the corresponding test flips to xpass.
#
# Three failure classes worth documenting in this dict if they recur:
#   - **signature mismatch**: tool method passes (self, input_str) but
#     the underlying function in tools/ expects (agent, x, y) positional
#     args. Fix: rewrite the function to accept (agent, input_str), parse
#     the JSON internally, validate required keys with friendly errors.
#   - **KeyError on missing input**: function does ``data['x']`` without
#     a guard. Fix: ``if 'x' not in data: return "x is required"``.
#   - **dead model import**: e.g. import of a model class that doesn't
#     exist. Fix: drop the @tool registration and stub the function
#     (model is genuinely missing) OR rewrite to use the right model.
_KNOWN_DRIFT: dict[tuple[str, str], str] = {}


def _all_agent_tool_pairs() -> List[Tuple[str, str]]:
    """Return ``[(agent_name, tool_name), ...]`` for every entry in
    ``CANONICAL_TOOLS`` minus ``_SMOKE_SKIP`` exclusions.

    Universal tools (``retrieve_workspace_context``, ``whoami``,
    ``get_workspace_info``) are NOT iterated — they're framework-
    provided and tested separately.
    """
    pairs: List[Tuple[str, str]] = []
    for agent_name, tool_names in sorted(CANONICAL_TOOLS.items()):
        skip = _SMOKE_SKIP.get(agent_name, set())
        for tool_name in sorted(tool_names):
            if tool_name in skip or tool_name in UNIVERSAL_TOOLS:
                continue
            pairs.append((agent_name, tool_name))
    return pairs


@pytest.fixture
def smoke_workspace(workspace_factory, user_factory, team_factory):
    """A real workspace + user + team with active_team_id set on the user.

    Function-scoped: each parametrized test gets a fresh workspace.
    With ~150 tests this is the bulk of the suite cost, but
    transaction rollback makes per-test setup safe.

    NOTE on running: the full suite (~150 tests) is heavy enough
    that running it as a single ``pytest`` invocation can OOM the
    test process. The test ID encodes the agent name, so per-agent
    runs are the easy chunking strategy::

        pytest -k 'workspace_agent' components/agents/tests/integration/test_tool_smoke_runtime.py

    Every tool that needs workspace context can succeed against this
    fixture; tools that need a task/budget/etc. id will return "X is
    required" or "X not found" — both are graceful, neither leaks a
    traceback.
    """
    user = user_factory()
    workspace = workspace_factory(owner=user)
    team = team_factory(workspace=workspace, created_by=user, members=[user])

    # Several timer/team tools read user.profile.active_team_id.
    profile = getattr(user, "profile", None)
    if profile is not None:
        profile.active_team_id = team.id
        profile.save(update_fields=["active_team"] if hasattr(profile, "active_team") else None)

    return {"user": user, "workspace": workspace, "team": team}


def _make_smoke_agent(agent_cls, *, smoke_workspace):
    """Build a minimal agent instance for smoke calls.

    Mirrors ``AgentTestCase.make_agent`` but as a pytest helper so
    Pattern E can use parametrized pytest tests.
    """
    user = smoke_workspace["user"]
    workspace = smoke_workspace["workspace"]

    fake_llm = MagicMock(name="fake_llm")
    fake_provider = MagicMock(name="fake_llm_provider")
    fake_provider.get_llm = MagicMock(return_value=fake_llm)

    fake_memory_service = MagicMock(name="fake_memory_service")
    fake_memory_service.get_memory = MagicMock(return_value=MagicMock())
    fake_memory_service.get_conversation_id = MagicMock(return_value=None)

    from components.agents.infrastructure.adapters.langchain import base as base_module

    with patch.object(
        base_module, "get_agent_memory_service", return_value=fake_memory_service
    ), patch.object(
        agent_cls, "_create_agent_executor", lambda self_inner: None, create=False
    ):
        agent = agent_cls(
            agent_id=str(uuid.uuid4()),
            user_id=str(user.id),
            workspace_id=str(workspace.id),
            llm_provider=fake_provider,
            default_user_id=str(user.id),
            default_user_email=user.email,
        )

    return agent


def _find_tool(agent, tool_name: str):
    """Return the StructuredTool whose ``.name`` matches.

    None means the tool is registered in CANONICAL_TOOLS but missing
    from the live agent's ``.tools`` list — Pattern C should already
    have caught that, so this is belt-and-suspenders.
    """
    for tool in getattr(agent, "tools", []) or []:
        if getattr(tool, "name", None) == tool_name:
            return tool
    return None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("agent_name", "tool_name"),
    _all_agent_tool_pairs(),
    ids=lambda v: v if isinstance(v, str) else "?",
)
def test_tool_smoke_run_does_not_leak_traceback(
    agent_name, tool_name, smoke_workspace, request
):
    """Calling a tool with empty JSON must not leak a traceback marker.

    The expectation is graceful failure: each tool either succeeds (if
    it doesn't need parameters) or returns a string like ``"X is
    required"`` / ``"X not found in this workspace"``. Anything that
    contains ``AttributeError`` / ``object has no attribute`` / etc.
    is implementation drift the LLM-facing prompt shouldn't see.
    """
    drift_reason = _KNOWN_DRIFT.get((agent_name, tool_name))
    if drift_reason:
        request.applymarker(
            pytest.mark.xfail(
                reason=f"Known drift queued for follow-up: {drift_reason}",
                strict=True,
            )
        )

    agent_cls = AgentRegistry.get_agent_class(agent_name)
    assert agent_cls is not None, (
        f"Agent {agent_name} is in CANONICAL_TOOLS but not registered."
    )

    agent = _make_smoke_agent(agent_cls, smoke_workspace=smoke_workspace)
    tool = _find_tool(agent, tool_name)
    assert tool is not None, (
        f"Tool {tool_name!r} not found on agent {agent_name}. "
        "CANONICAL_TOOLS expects it but the agent didn't register it."
    )

    # Call with empty JSON — the smallest input any tool should accept.
    try:
        result = tool.func("{}")
    except Exception as exc:  # pylint: disable=broad-except
        pytest.fail(
            f"Tool {agent_name}.{tool_name} raised an unhandled exception "
            f"on smoke input: {type(exc).__name__}: {exc}\n"
            "Tools must catch their own errors and return a string."
        )

    assert isinstance(result, str), (
        f"Tool {agent_name}.{tool_name} returned non-string: "
        f"{type(result).__name__} (value: {result!r})"
    )

    leaked = [marker for marker in _TRACEBACK_MARKERS if marker in result]
    assert not leaked, (
        f"Tool {agent_name}.{tool_name} leaked traceback marker(s) "
        f"{leaked} into its response.\n"
        f"This indicates implementation drift — the tool body references "
        f"a model field, model class, or method that doesn't exist (the "
        f"project.name vs project.title class of bug).\n\n"
        f"Full response: {result[:500]}"
    )
