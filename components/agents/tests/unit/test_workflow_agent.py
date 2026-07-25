"""WorkflowAgent tests (AgentTestCase harness — no real LLM).

Pins the registration + alias contract, the tool's risk tier, and the core
behaviour: draft_workflow reuses the workflow context's draft use case, persists
a DRAFT (never publishes), and returns the steps + where to open it. The draft
use case + persistence are mocked — the agent's job is orchestration, not the LLM.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from components.agents.infrastructure.adapters.langchain.agents.workflow_agent import (
    WorkflowAgent,
)
from components.agents.tests.agent_test_case import AgentTestCase

_DRAFT_PROVIDER = (
    "components.workflow.application.providers.workflow_draft_provider.WorkflowDraftProvider.build_draft_use_case"
)
_SERVICE = "components.workflow.application.service.WorkflowService"

_VALID_GRAPH = {
    "nodes": [
        {"id": "start", "type": "start", "label": "Critical finding raised"},
        {"id": "notify", "type": "message", "label": "Alert the SOC"},
        {"id": "triage", "type": "ai", "label": "AI triage"},
        {"id": "end", "type": "end", "label": "End"},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "notify", "label": None},
        {"id": "e2", "from": "notify", "to": "triage", "label": None},
        {"id": "e3", "from": "triage", "to": "end", "label": None},
    ],
}


class _FakeWorkflow:
    def __init__(self, wf_id: str) -> None:
        self.id = wf_id


class _FakeUseCase:
    def __init__(self, *, available=True, result=None) -> None:
        self._available = available
        self._result = result or {}

    def is_available(self):
        return self._available

    def execute(self, *, prompt, workspace_id):
        self._last = {"prompt": prompt, "workspace_id": workspace_id}
        return self._result


class WorkflowAgentTests(AgentTestCase):
    def test_registered_under_canonical_name_and_aliases(self):
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        for name in ("workflow_agent", "workflow", "workflows", "playbook", "automation"):
            self.assertIs(AgentRegistry.get_agent_class(name), WorkflowAgent)

    def test_draft_tool_registered_as_reversible_write(self):
        from components.agents.application.policies.tool_risk import ToolRisk, normalize_risk

        agent = self.make_agent(WorkflowAgent)
        by_name = {t.name: t for t in agent.tools}
        self.assertIn("draft_workflow", by_name)
        meta = WorkflowAgent.draft_workflow._agent_tool_meta
        self.assertEqual(normalize_risk(meta["risk"]), ToolRisk.REVERSIBLE_WRITE)

    def test_draft_creates_a_draft_workflow_and_returns_steps(self):
        agent = self.make_agent(WorkflowAgent)
        use_case = _FakeUseCase(
            result={"graph": _VALID_GRAPH, "valid": True, "name": "Critical alert → triage", "goal": "security"}
        )
        with (
            patch(_DRAFT_PROVIDER, return_value=use_case),
            patch(_SERVICE) as service_cls,
            patch.object(WorkflowAgent, "_resolve_user", return_value=None),
        ):
            service_cls.return_value.create_workflow.return_value = _FakeWorkflow("wf-1")
            out = agent.draft_workflow("when a critical finding lands, alert the SOC and run AI triage")

        payload = json.loads(out)
        assert payload["workflow_id"] == "wf-1"
        assert payload["status"] == "draft"
        assert payload["valid"] is True
        assert "Alert the SOC" in payload["steps"]
        # Persisted as a DRAFT (never published) via the workflow service.
        create = service_cls.return_value.create_workflow
        create.assert_called_once()
        assert create.call_args.kwargs["status"] == "draft"
        assert create.call_args.kwargs["graph"] == _VALID_GRAPH

    def test_invalid_draft_still_saves_and_flags_fixes(self):
        agent = self.make_agent(WorkflowAgent)
        use_case = _FakeUseCase(
            result={
                "graph": _VALID_GRAPH,
                "valid": False,
                "errors": [{"code": "branch_missing_label", "message": "x"}],
                "name": "Half-built",
                "goal": "security",
            }
        )
        with (
            patch(_DRAFT_PROVIDER, return_value=use_case),
            patch(_SERVICE) as service_cls,
            patch.object(WorkflowAgent, "_resolve_user", return_value=None),
        ):
            service_cls.return_value.create_workflow.return_value = _FakeWorkflow("wf-2")
            out = agent.draft_workflow("do something vague")

        payload = json.loads(out)
        assert payload["valid"] is False
        assert "fixes" in payload["message"].lower()

    def test_requires_a_description(self):
        agent = self.make_agent(WorkflowAgent)
        out = agent.draft_workflow("   ")
        assert "describe" in out.lower()

    def test_unconfigured_environment_is_reported(self):
        agent = self.make_agent(WorkflowAgent)
        with patch(_DRAFT_PROVIDER, return_value=_FakeUseCase(available=False)):
            out = agent.draft_workflow("build a triage playbook")
        assert "not configured" in out.lower()

    def test_system_message_appends_versioned_registry_prompt(self):
        """The base convention auto-appends ``workflow_agent.system`` — the agent
        carries no hardcoded ``_build_system_message`` override.

        Guards the ``<agent_slug>.system`` convention: the drafting discipline
        reaches the LLM from the registry (versioned, hygiene-tested, rollback-able),
        not from a per-agent string that would drift.
        """
        from components.agents.infrastructure.prompts.registry import PromptRegistry

        agent = self.make_agent(WorkflowAgent)
        system_message = agent._build_system_message()

        # The registered specialist prompt is present verbatim in the assembled
        # message (base role/profile first, specialist addendum appended).
        registered = PromptRegistry.get("workflow_agent.system")
        assert registered in system_message
        assert "<workflow_drafting_rules>" in system_message
        # It is appended, not prepended — the base role blurb still leads.
        assert system_message.index("You are the") < system_message.index("<workflow_drafting_rules>")
        # The agent opts in purely via the registry — no override on the class.
        assert "_build_system_message" not in vars(WorkflowAgent)
