"""Unit tests for the deepagents RubricMiddleware wiring (deep/rubric.py).

Covers the gating rules (settings/config/agent-type), the bounded-iterations
cap, and the grader's grounded-verifier tool. The middleware object itself is
only constructed when ``deepagents`` is importable; the gating logic tests run
regardless.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.deep import rubric as rubric_mod
from components.agents.infrastructure.adapters.langchain.deep.rubric import (
    MAX_ITERATIONS_CAP,
    build_grader_verifier_tool,
    rubric_middleware_enabled,
)


class TestGating:
    def test_disabled_by_default(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = False
        assert rubric_middleware_enabled({}) is False
        assert rubric_middleware_enabled(None) is False

    def test_global_setting_enables(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = True
        assert rubric_middleware_enabled({}) is True

    def test_agent_config_enables(self, settings):
        settings.DEEP_RUBRIC_MIDDLEWARE_ENABLED = False
        assert rubric_middleware_enabled({"rubric_middleware": True}) is True
        assert rubric_middleware_enabled({"rubric_middleware": {"max_iterations": 1}}) is True


def _fake_agent(agent_type="triage_agent", workspace_id="ws-1"):
    provider = SimpleNamespace(get_llm=lambda **kw: SimpleNamespace(kind="llm", **kw))
    agent = SimpleNamespace(
        config={"agent_type": agent_type},
        workspace_id=workspace_id,
        agent_id="agent-1",
        _resolve_llm_provider=lambda: provider,
    )
    return agent


class TestBuildRubricMiddleware:
    def test_none_for_non_critic_agent_type(self):
        mw = rubric_mod.build_rubric_middleware(agent=_fake_agent("workspace_agent"), config={})
        assert mw is None

    def test_builds_for_triage_agent_with_bounded_iterations(self):
        deepagents_rubric = pytest.importorskip("deepagents.middleware.rubric")
        mw = rubric_mod.build_rubric_middleware(
            agent=_fake_agent("triage_agent"),
            config={"max_iterations": 99},  # must be capped to <= 2
        )
        assert mw is not None
        assert isinstance(mw, deepagents_rubric.RubricMiddleware)
        max_iter = getattr(mw, "max_iterations", None)
        assert max_iter is not None and max_iter <= MAX_ITERATIONS_CAP

    def test_iterations_cap_constant_is_two(self):
        # The migration plan hard-requires max_iterations <= 2.
        assert MAX_ITERATIONS_CAP == 2


class TestGraderVerifierTool:
    def test_tool_name_is_stable(self):
        tool = build_grader_verifier_tool(_fake_agent())
        assert tool.name == "verify_suggestion_grounded"

    def test_no_task_id_reports_no_evidence(self):
        tool = build_grader_verifier_tool(_fake_agent())
        payload = json.loads(tool.func(suggestion_text="fix the ImportError in components.foo"))
        assert payload["grounded"] is None
        assert "No finding evidence" in payload["reason"]

    @pytest.mark.django_db
    def test_grounded_verdict_from_real_finding(self):
        from infrastructure.persistence.project.models import Task

        pytest.importorskip("langchain_core")
        # Minimal finding row: triage evidence names a concrete symbol.
        task = Task.objects.create(
            title="Triage: ImportError in AiEmbeddingsProvider",
            source_type="ai.log_watch",
            metadata={
                "payload": {
                    "message": "ImportError: cannot import name 'AiEmbeddingsProvider'",
                    "evidence": [{"detail": "AiEmbeddingsProvider raised ImportError"}],
                }
            },
        )
        agent = _fake_agent(workspace_id=str(task.workspace_id) if task.workspace_id else "ws-1")
        # Align the agent's workspace scope with the row we created.
        agent.workspace_id = task.workspace_id

        tool = build_grader_verifier_tool(agent)
        grounded = json.loads(
            tool.func(
                suggestion_text="Fix the AiEmbeddingsProvider import in the knowledge factory.",
                task_id=str(task.id),
            )
        )
        assert grounded["grounded"] is True

        ungrounded = json.loads(
            tool.func(
                suggestion_text="Investigate further and monitor the logs for issues.",
                task_id=str(task.id),
            )
        )
        assert ungrounded["grounded"] is False
        assert ungrounded["reason"]
