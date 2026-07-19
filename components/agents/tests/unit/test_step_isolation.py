"""Unit tests for deep-run step isolation."""

from components.agents.domain.services.step_isolation import (
    StepContext,
    build_step_contexts,
)


class TestStepContext:
    def test_as_run_context(self):
        ctx = StepContext(
            step_id="step-1",
            task_title="Create budget",
            run_id="run-abc",
            workspace_id="ws-1",
            user_id="user-1",
            agent_type="budget_agent",
            allowed_tools=frozenset({"list_budgets", "create_budget"}),
            conversation_id="conv-xyz",
        )
        run_ctx = ctx.as_run_context()
        assert run_ctx["run_id"] == "run-abc"
        assert run_ctx["conversation_id"] == "conv-xyz"
        assert "list_budgets" in run_ctx["allowed_tools"]
        assert run_ctx["memory_limits"]["max_messages"] == 20

    def test_build_step_prompt_prefix(self):
        ctx = StepContext(
            step_id="step-2",
            task_title="Analyze expenses",
            run_id="run-abc",
            workspace_id="ws-1",
            user_id="user-1",
            agent_type="financial_agent",
            step_instructions="Review Q4 expenses",
            prior_step_summaries=["Created budget of $50k"],
        )
        prefix = ctx.build_step_prompt_prefix()
        assert "Review Q4 expenses" in prefix
        assert "Created budget of $50k" in prefix


class TestBuildStepContexts:
    def test_builds_contexts_for_each_task(self):
        tasks = [
            {"id": "t1", "title": "Step 1", "description": "Do first thing"},
            {"id": "t2", "title": "Step 2", "description": "Do second thing"},
            {"id": "t3", "title": "Step 3"},
        ]
        contexts = build_step_contexts(
            run_id="run-123",
            workspace_id="ws-1",
            user_id="user-1",
            agent_type="workspace_agent",
            tasks=tasks,
        )
        assert len(contexts) == 3
        assert contexts[0].step_id == "t1"
        assert contexts[1].step_id == "t2"
        assert contexts[2].step_id == "t3"

    def test_each_step_gets_own_conversation_id(self):
        tasks = [
            {"id": "t1", "title": "A"},
            {"id": "t2", "title": "B"},
        ]
        contexts = build_step_contexts(
            run_id="run-x",
            workspace_id="ws-1",
            user_id="user-1",
            agent_type="test",
            tasks=tasks,
        )
        assert contexts[0].conversation_id != contexts[1].conversation_id

    def test_prior_summaries_accumulate(self):
        tasks = [
            {"title": "First"},
            {"title": "Second"},
            {"title": "Third"},
        ]
        contexts = build_step_contexts(
            run_id="run-y",
            workspace_id="ws-1",
            user_id="user-1",
            agent_type="test",
            tasks=tasks,
        )
        assert len(contexts[0].prior_step_summaries) == 0
        assert len(contexts[1].prior_step_summaries) == 1
        assert len(contexts[2].prior_step_summaries) == 2

    def test_global_tool_restrictions(self):
        tasks = [
            {"id": "t1", "title": "A", "allowed_tools": ["list_budgets", "create_budget"]},
        ]
        contexts = build_step_contexts(
            run_id="run-z",
            workspace_id="ws-1",
            user_id="user-1",
            agent_type="test",
            tasks=tasks,
            global_allowed_tools=frozenset({"list_budgets", "get_budget"}),
        )
        # Intersection: only list_budgets is in both
        assert "list_budgets" in contexts[0].allowed_tools
        assert "create_budget" not in contexts[0].allowed_tools
