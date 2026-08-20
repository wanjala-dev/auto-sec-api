"""SEE-203 — the per-call tool risk gate (``_risk_gated``).

The gate wraps a promoted tool and enforces its tier against the run context:
an autonomous run is denied irreversible tools; an irreversible tool is denied
to any caller until the run carries ``approval_granted``; read/reversible tools
pass through. Composes with the SEE-201 autonomous-principal identity.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.infrastructure.adapters.langchain.base import _risk_gated
from infrastructure.persistence.ai.models import AITeammateProfile


def _gate(tool_name, agent, explicit_risk=None):
    def _tool(*args, **kwargs):
        return "RAN"

    return _risk_gated(_tool, tool_name, explicit_risk, agent)()


@pytest.mark.django_db
class TestInteractiveCaller:
    def _human_agent(self, config=None):
        # A bare UUID that is not an AITeammateProfile.user → not autonomous.
        return SimpleNamespace(user_id=str(uuid4()), workspace_id=str(uuid4()), config=config or {})

    def test_read_tool_runs(self):
        assert _gate("list_open_findings", self._human_agent()) == "RAN"

    def test_irreversible_denied_without_approval(self):
        result = _gate("open_draft_pr", self._human_agent(), ToolRisk.IRREVERSIBLE)
        assert "approval" in result.lower()

    def test_irreversible_runs_with_approval(self):
        agent = self._human_agent(config={"approval_granted": True})
        assert _gate("open_draft_pr", agent, ToolRisk.IRREVERSIBLE) == "RAN"

    def test_explicit_decorator_risk_overrides_registry(self):
        # ``delete_task`` is reversible_write in the central registry — an
        # explicit decorator tier wins, so the gate now demands approval.
        agent = self._human_agent()
        assert "approval" in _gate("delete_task", agent, ToolRisk.IRREVERSIBLE).lower()


@pytest.mark.django_db
class TestAutonomousCaller:
    def _ai_agent(self, workspace_factory, user_factory, config=None):
        workspace = workspace_factory()
        ai_user = user_factory()
        AITeammateProfile.objects.create(workspace=workspace, user=ai_user)
        return SimpleNamespace(
            user_id=str(ai_user.id),
            workspace_id=str(workspace.id),
            config=config or {},
        )

    def test_irreversible_denied_even_with_approval(self, workspace_factory, user_factory):
        agent = self._ai_agent(workspace_factory, user_factory, config={"approval_granted": True})

        result = _gate("open_draft_pr", agent, ToolRisk.IRREVERSIBLE)

        assert "Autonomous" in result

    def test_reversible_tool_runs_for_autonomous(self, workspace_factory, user_factory):
        agent = self._ai_agent(workspace_factory, user_factory)

        assert _gate("delete_task", agent) == "RAN"
