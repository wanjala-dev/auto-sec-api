"""Integration test: the rubric grader's grounded-verifier tool against a REAL finding row.

Moved out of ``tests/unit/test_rubric_middleware_wiring.py`` — it creates a
``Task`` finding through the ORM (``@pytest.mark.django_db``), which makes it
an integration test per the testing skill's HARD RULE 2 (unit tests are
DB-free). The pure gating / collector / tool-shape tests stay in the unit
file.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.deep.rubric import (
    build_grader_verifier_tool,
)


def _fake_agent(agent_type="triage_agent", workspace_id="ws-1"):
    provider = SimpleNamespace(get_llm=lambda **kw: SimpleNamespace(kind="llm", **kw))
    return SimpleNamespace(
        config={"agent_type": agent_type},
        workspace_id=workspace_id,
        agent_id="agent-1",
        _resolve_llm_provider=lambda: provider,
    )


@pytest.mark.django_db
def test_grounded_verdict_from_real_finding(workspace_factory, team_factory, user_factory):
    from infrastructure.persistence.project.models import Task

    pytest.importorskip("langchain_core")
    user = user_factory()
    workspace = workspace_factory()
    team = team_factory(workspace=workspace)
    # Minimal finding row: triage evidence names a concrete symbol.
    task = Task.objects.create(
        workspace=workspace,
        team=team,
        created_by=user,
        title="Triage: ImportError in AiEmbeddingsProvider",
        source_type="ai.log_watch",
        metadata={
            "payload": {
                "message": "ImportError: cannot import name 'AiEmbeddingsProvider'",
                "evidence": [{"detail": "AiEmbeddingsProvider raised ImportError"}],
            }
        },
    )
    agent = _fake_agent(workspace_id=str(workspace.id))
    agent.workspace_id = workspace.id

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
