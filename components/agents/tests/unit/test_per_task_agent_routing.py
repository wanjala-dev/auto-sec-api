"""Pin per-task specialist agent routing on the deep-run path.

Background: 2026-05-08 incident — Henry asked "how many budgets do we
have?" and got back "0" despite there being 2 active budgets in the
DB. Root cause: the deep-run planner emitted a single task and the
runner dispatched it to ``workspace_agent`` (the chat's default
``agent_type``), which has zero budget tools. The agent fabricated "0"
from membership/team metadata it could see.

The fix routes each ``TaskSpec`` to a specialist agent the planner
chose ("budget_agent" for budget tasks, "sponsorship_agent" for
sponsor tasks, etc.). Tests below pin every link in the chain so a
future revert fails loudly here instead of silently giving wrong
answers in production.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestTaskSpecAgentTypeField:
    def test_task_spec_accepts_agent_type(self):
        from components.agents.domain.value_objects.plan_schemas import TaskSpec

        task = TaskSpec(title="count budgets", agent_type="budget_agent")
        assert task.agent_type == "budget_agent"

    def test_task_spec_agent_type_defaults_to_none_for_back_compat(self):
        """Older callers / tests that build TaskSpec without agent_type
        keep working — the field is optional. The runner falls through
        to the chat's default agent_type when None.
        """
        from components.agents.domain.value_objects.plan_schemas import TaskSpec

        task = TaskSpec(title="something")
        assert task.agent_type is None


class TestBuildPlanFromActionsThreadsAgentType:
    def test_planner_action_dict_agent_type_is_kept(self):
        from components.agents.domain.services.deep.planners import (
            build_plan_from_actions,
        )

        actions = [
            {"title": "List the workspace's budgets", "agent_type": "budget_agent"},
            {"title": "Summarise sponsors", "agent_type": "sponsorship_agent"},
            {"title": "Generic chat reply"},  # no agent_type → None
        ]
        plan = build_plan_from_actions(plan_id="p-1", goal="multi-domain", actions=actions)
        assert [t.agent_type for t in plan.tasks] == [
            "budget_agent",
            "sponsorship_agent",
            None,
        ]

    def test_empty_string_agent_type_normalises_to_none(self):
        """The LLM occasionally emits ``"agent_type": ""`` when it
        doesn't know which specialist to pick. Treat that the same as
        omitted so the runner falls back to the chat's default.
        """
        from components.agents.domain.services.deep.planners import (
            build_plan_from_actions,
        )

        plan = build_plan_from_actions(
            plan_id="p-empty",
            goal="g",
            actions=[{"title": "anything", "agent_type": ""}],
        )
        assert plan.tasks[0].agent_type is None


class TestPlannerSystemPromptIncludesAgentCatalog:
    def test_prompt_template_has_catalog_placeholder(self):
        from components.agents.infrastructure.adapters.langchain.deep import (
            llm_planner,
        )

        # Template uses {agent_catalog} substitution. If a future edit
        # hardcodes the agent list back into the prompt, this will
        # fail and the catalog will go stale.
        assert "{agent_catalog}" in llm_planner.SYSTEM_PROMPT_TEMPLATE

    def test_resolved_prompt_lists_known_specialists(self):
        from components.agents.infrastructure.adapters.langchain.deep.llm_planner import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt()
        # Each registered agent should appear by name. budget_agent +
        # workspace_agent are the bare-minimum specialists for the
        # 2026-05-08 incident class to be fixable.
        assert "budget_agent" in prompt, (
            "Planner can't pick budget_agent if it doesn't appear in "
            "the catalog. The 2026-05-08 hallucination came back."
        )
        assert "workspace_agent" in prompt
        # Guidance about WHY routing matters must stay — a future
        # rewrite that drops the per-task instruction will let the LLM
        # silently regress.
        assert "agent_type" in prompt.lower()
        assert "specialist" in prompt.lower()


class TestRunnerDispatchesPerTask:
    """Verify the runner builds workers per ``agent_type`` and routes
    each task accordingly.

    Source-inspection rather than execution because ``execute_plan_once``
    writes ``DeepRun`` rows and runs the LangGraph orchestrator —
    spinning that up just to assert which agent_type a worker was
    built with adds far more surface area than the ~20 lines of
    routing logic we actually care about. If the implementation is
    refactored, these assertions fail loudly with a specific message
    so the rewrite has to keep the contract.
    """

    def test_runner_builds_worker_per_task_agent_type(self):
        import inspect

        from components.agents.infrastructure.adapters.langchain.deep import (
            runner,
        )

        source = inspect.getsource(runner.execute_plan_once)

        # The dispatch must read ``task.agent_type`` to pick the
        # specialist. If a future refactor goes back to a single
        # ``base_worker = build_worker_from_agent(agent_type=agent_type, ...)``
        # closed over the chat-level ``agent_type``, the 2026-05-08
        # hallucination class is back.
        assert "task.agent_type" in source or "getattr(task, \"agent_type\"" in source, (
            "Runner must read ``task.agent_type`` to route per task. "
            "Otherwise every task lands on the chat's default agent and "
            "specialist tools are unreachable."
        )

        # The worker cache prevents rebuilding the same agent on every
        # task — without it a 5-task plan all routed to budget_agent
        # would build 5 BudgetAgent instances. The cache is keyed on
        # agent_type; if it's removed, this assertion catches it.
        assert "_worker_cache" in source, (
            "Per-task routing must cache workers by agent_type. "
            "Without the cache, every task rebuilds its agent — "
            "budgets blow up on multi-task plans."
        )

        # Fallback when the planner emits a task without agent_type
        # (older plans, vague goals): use the chat's default
        # ``agent_type``. Keeps back-compat for callers that don't
        # know about per-task routing yet.
        assert "or agent_type" in source or 'or "agent_type"' in source, (
            "Runner must fall back to the chat's default agent_type "
            "when a task has no explicit agent_type. Otherwise older "
            "planners regress."
        )
