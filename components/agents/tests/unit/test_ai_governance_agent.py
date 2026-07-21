"""AiGovernanceAgent tests (AgentTestCase harness — no real LLM, services mocked).

Pins the agent's registration + alias contract, that every tool is a
READ-tier 1:1 wrapper over ``ai_governance_service`` (returning the service
data verbatim as JSON), the honest failure degradation, and the system
prompt's governance rules (assessor-not-actor, no secrets, honest gaps).
The kill switch must NEVER appear as a tool — that is the constitutional
line this file guards.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from components.agents.infrastructure.adapters.langchain.agents.ai_governance_agent import (
    AiGovernanceAgent,
)
from components.agents.tests.agent_test_case import AgentTestCase

_SERVICE = "components.agents.application.services.ai_governance_service"

_TOOL_NAMES = {
    "get_ai_activity",
    "get_capability_grants",
    "get_hitl_ledger",
    "get_credential_inventory",
    "get_kill_switch_status",
    "get_governance_report",
}


def _fake_activity(**overrides):
    data = {
        "window_days": 7,
        "computed_at": "2026-07-20T12:00:00+00:00",
        "runs": {
            "total": 3,
            "by_status": {"completed": 2, "failed": 1},
            "by_source": {"chat": 2, "detector": 1},
            "sample_run_ids": ["run-1", "run-2", "run-3"],
            "no_data": False,
        },
        "tool_calls": {
            "total": 5,
            "by_tool": {"list_open_findings": 3, "open_draft_pr": 2},
            "by_agent": {"TriageAgent": 5},
            "by_risk_tier": {"read": 3, "irreversible": 2},
            "no_data": False,
        },
        "no_data": False,
    }
    data.update(overrides)
    return data


def _fake_grants():
    return {
        "computed_at": "2026-07-20T12:00:00+00:00",
        "agents": [
            {
                "agent_id": "agent-1",
                "agent_type": "triage_agent",
                "status": "active",
                "capabilities": {"open_draft_pr": True},
                "enabled_capabilities": ["open_draft_pr"],
                "power_flags": {"rubric_middleware": True},
                "grant_history_recorded": False,
                "grant_audit_entries": [],
            }
        ],
        "agent_total": 1,
        "enabled_capability_total": 1,
        "agents_with_grant_history": 0,
        "audit_note": "Capability changes are audited from the governance slice onward.",
        "no_data": False,
    }


def _fake_ledger():
    return {
        "window_days": 30,
        "draft_prs_opened": {"count": 1, "items": [{"task_id": "task-1"}], "undated_records": 0, "no_data": False},
        "approvals": {"granted": 1, "denials_recorded": False, "note": "Denied approvals are not recorded."},
        "no_data": False,
    }


def _fake_credentials():
    return {
        "computed_at": "2026-07-20T12:00:00+00:00",
        "github_connections": {
            "count": 1,
            "items": [{"id": "conn-1", "has_token": True, "repo_allowlist": ["o/r"], "repo_allowlist_count": 1}],
            "no_data": False,
        },
        "secrets_note": "Token material is never read into this report.",
        "no_data": False,
    }


def _fake_kill_switch():
    return {
        "computed_at": "2026-07-20T12:00:00+00:00",
        "workspace_found": True,
        "ai_teammate_enabled": True,
        "emergency_flag_engaged": False,
        "ai_halted": False,
        "teammate_profile": {"status": "active", "is_enabled": True},
        "agents": {"total": 2, "active": 1, "by_status": {"active": 1, "paused": 1}, "items": [], "no_data": False},
        "would_stop": {"active_agents": 1, "in_flight_deep_runs": 0, "scheduled_detector_cycles": True},
        "no_data": False,
    }


class AiGovernanceAgentRegistrationTests(AgentTestCase):
    def test_registered_under_canonical_name_and_aliases(self):
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        for name in ("ai_governance_agent", "ai_governance", "governance", "ai_audit", "ai_activity"):
            self.assertIs(AgentRegistry.get_agent_class(name), AiGovernanceAgent)

    def test_all_governance_tools_are_registered_and_read_only(self):
        from components.agents.application.policies.tool_risk import ToolRisk

        agent = self.make_agent(AiGovernanceAgent)
        tool_names = {t.name for t in agent.tools}
        self.assertTrue(_TOOL_NAMES.issubset(tool_names), f"missing: {_TOOL_NAMES - tool_names}")
        for method_name in _TOOL_NAMES:
            meta = getattr(AiGovernanceAgent, method_name)._agent_tool_meta
            self.assertEqual(meta["risk"], ToolRisk.READ, f"{method_name} must be READ risk")

    def test_no_kill_switch_write_tool_exists(self):
        # Constitutional: the agent is an assessor, not an actor. No tool
        # may be able to flip / pause / resume anything.
        agent = self.make_agent(AiGovernanceAgent)
        for tool_obj in agent.tools:
            for verb in ("set_", "flip_", "pause_", "resume_", "disable_", "enable_", "toggle_"):
                self.assertFalse(
                    tool_obj.name.startswith(verb),
                    f"governance agent must not expose a write-shaped tool: {tool_obj.name}",
                )


class AiGovernanceAgentToolTests(AgentTestCase):
    def test_get_ai_activity_returns_service_data(self):
        self.mock_llm_chooses("get_ai_activity", "")
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.ai_activity", return_value=_fake_activity()) as fn:
            result = agent.agent_executor.invoke({"input": "what has the AI been doing?"})

        self.assert_tool_called("get_ai_activity")
        fn.assert_called_once_with(agent.workspace_id, window_days=7)
        payload = json.loads(result["output"])
        self.assertEqual(payload["runs"]["by_source"], {"chat": 2, "detector": 1})
        self.assertEqual(payload["tool_calls"]["by_risk_tier"]["irreversible"], 2)

    def test_get_ai_activity_honours_window_days(self):
        self.mock_llm_chooses("get_ai_activity", '{"window_days": 30}')
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.ai_activity", return_value=_fake_activity(window_days=30)) as fn:
            agent.agent_executor.invoke({"input": "last 30 days"})
        fn.assert_called_once_with(agent.workspace_id, window_days=30)

    def test_get_capability_grants_returns_service_data(self):
        self.mock_llm_chooses("get_capability_grants", "")
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.capability_grants", return_value=_fake_grants()) as fn:
            result = agent.agent_executor.invoke({"input": "which permissions does the AI have?"})

        fn.assert_called_once_with(agent.workspace_id)
        payload = json.loads(result["output"])
        self.assertEqual(payload["agents"][0]["enabled_capabilities"], ["open_draft_pr"])
        self.assertFalse(payload["agents"][0]["grant_history_recorded"])

    def test_get_hitl_ledger_defaults_to_thirty_day_window(self):
        self.mock_llm_chooses("get_hitl_ledger", "")
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.hitl_ledger", return_value=_fake_ledger()) as fn:
            result = agent.agent_executor.invoke({"input": "recent approvals?"})

        fn.assert_called_once_with(agent.workspace_id, window_days=30)
        payload = json.loads(result["output"])
        self.assertFalse(payload["approvals"]["denials_recorded"])

    def test_get_credential_inventory_returns_service_data(self):
        self.mock_llm_chooses("get_credential_inventory", "")
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.credential_inventory", return_value=_fake_credentials()) as fn:
            result = agent.agent_executor.invoke({"input": "what can the AI reach?"})

        fn.assert_called_once_with(agent.workspace_id)
        payload = json.loads(result["output"])
        self.assertTrue(payload["github_connections"]["items"][0]["has_token"])
        self.assertNotIn("token_ciphertext", result["output"])

    def test_get_kill_switch_status_returns_service_data(self):
        self.mock_llm_chooses("get_kill_switch_status", "")
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.kill_switch_status", return_value=_fake_kill_switch()) as fn:
            result = agent.agent_executor.invoke({"input": "can we stop the AI?"})

        fn.assert_called_once_with(agent.workspace_id)
        payload = json.loads(result["output"])
        self.assertFalse(payload["ai_halted"])
        self.assertEqual(payload["would_stop"]["active_agents"], 1)

    def test_get_governance_report_composes_service_report(self):
        report = {
            "window_days": 7,
            "ai_activity": _fake_activity(),
            "capability_grants": _fake_grants(),
            "hitl_ledger": _fake_ledger(),
            "credential_inventory": _fake_credentials(),
            "kill_switch_status": _fake_kill_switch(),
        }
        self.mock_llm_chooses("get_governance_report", "")
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.governance_report", return_value=report) as fn:
            result = agent.agent_executor.invoke({"input": "full governance report"})

        fn.assert_called_once_with(agent.workspace_id, window_days=7)
        payload = json.loads(result["output"])
        self.assertEqual(
            set(payload),
            {
                "window_days",
                "ai_activity",
                "capability_grants",
                "hitl_ledger",
                "credential_inventory",
                "kill_switch_status",
            },
        )

    def test_tool_failure_degrades_to_message_not_raise(self):
        self.mock_llm_chooses("get_ai_activity", "")
        agent = self.make_agent(AiGovernanceAgent)
        with patch(f"{_SERVICE}.ai_activity", side_effect=RuntimeError("db down")):
            result = agent.agent_executor.invoke({"input": "activity?"})

        self.assertIn("Could not compute AI activity", result["output"])


class AiGovernanceAgentPromptTests(AgentTestCase):
    def test_system_prompt_carries_governance_rules(self):
        agent = self.make_agent(AiGovernanceAgent)
        prompt = agent._build_system_message()

        self.assertIn("ASSESSOR, not an actor", prompt)
        self.assertIn("Answer ONLY from tool output", prompt)
        self.assertIn("Never output secret material", prompt)
        self.assertIn("grant_history_recorded=false", prompt)
        self.assertIn("denials_recorded=false", prompt)
        self.assertIn("no_data", prompt)
        self.assertIn("irreversible", prompt)
