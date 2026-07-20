"""PostureAgent tests (AgentTestCase harness — no real LLM, services mocked).

Pins the agent's registration + alias contract, that every tool is a 1:1
wrapper over ``posture_service`` (returning the service data verbatim as
JSON), the persona lensing contract of ``get_posture_report`` (engineer =
drill-down with finding ids, executive = NACD sections, same facts), and the
system prompt's honesty rules (CTEM frame, no composite score, no-data
flagging).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from components.agents.infrastructure.adapters.langchain.agents.posture_agent import (
    PostureAgent,
)
from components.agents.tests.agent_test_case import AgentTestCase

_SERVICE = "components.agents.application.services.posture_service"


def _fake_findings(**overrides):
    data = {
        "window_days": 7,
        "computed_at": "2026-07-20T12:00:00+00:00",
        "open_findings": {
            "total": 3,
            "by_severity": {"high": 2, "low": 1},
            "by_kind": {"ai.log_watch": 3},
            "sample_task_ids": ["task-1", "task-2", "task-3"],
        },
        "needs_human_backlog": {"count": 1, "sample_task_ids": ["task-3"]},
        "oldest_untriaged_age_hours": 48.0,
        "oldest_untriaged_task_id": "task-1",
        "triaged": {"last_24h": 1, "last_window": 2},
        "toil": {"handled_total": 2, "auto_triaged": 1, "escalated_to_human": 1, "auto_absorption_rate": 0.5},
        "no_data": False,
    }
    data.update(overrides)
    return data


def _fake_kpis():
    return {
        "window_days": 7,
        "triage_latency_by_severity": {
            sev: {"median_hours": 1.5, "band_hours": band, "within_band": True, "sample_count": 2, "no_data": False}
            for sev, band in (("critical", 1.0), ("high", 2.0), ("medium", 4.0), ("low", 8.0))
        },
        "acknowledgment_latency": {"median_hours": 0.5, "sample_count": 2, "no_data": False},
        "benchmark_source": "Prophet Security SOC metrics benchmarks",
        "no_data": False,
    }


def _fake_fleet():
    return {
        "window_days": 7,
        "deep_runs": {"total": 4, "completed": 3, "failed": 1, "in_flight": 0, "success_rate": 0.75, "no_data": False},
        "rubric_verdicts": {"graded_total": 2, "by_verdict": {"satisfied": 2}, "pass_rate": 1.0, "no_data": False},
        "cost": {
            "total_cost_usd": 0.42,
            "cost_per_day_usd": 0.06,
            "priced_records": 4,
            "unpriced_records": 0,
            "no_data": False,
        },
        "human_feedback": {"up": 3, "down": 1, "total": 4, "up_ratio": 0.75, "no_data": False},
        "dispatches": {"handled_findings": 2, "by_agent": {"triage_agent": 2}, "no_data": False},
    }


def _fake_outlook():
    return {
        "findings_created": {"this_week": 5, "last_week": 3, "delta": 2, "pct_change": 0.6667, "direction": "rising"},
        "needs_human_escalations": {"this_week": 1, "last_week": 0, "delta": 1},
        "needs_human_backlog_now": 1,
        "no_data": False,
    }


class PostureAgentRegistrationTests(AgentTestCase):
    def test_registered_under_canonical_name_and_aliases(self):
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        for name in ("posture_agent", "posture", "security_posture", "posture_review", "soc_posture"):
            self.assertIs(AgentRegistry.get_agent_class(name), PostureAgent)

    def test_all_posture_tools_are_registered_and_read_only(self):
        from components.agents.application.policies.tool_risk import ToolRisk

        agent = self.make_agent(PostureAgent)
        tool_names = {t.name for t in agent.tools}
        expected = {
            "get_findings_posture",
            "get_response_kpis",
            "get_fleet_health",
            "get_forward_outlook",
            "get_posture_report",
        }
        self.assertTrue(expected.issubset(tool_names), f"missing: {expected - tool_names}")
        for method_name in expected:
            meta = getattr(PostureAgent, method_name)._agent_tool_meta
            self.assertEqual(meta["risk"], ToolRisk.READ, f"{method_name} must be READ risk")


class PostureAgentToolTests(AgentTestCase):
    def test_get_findings_posture_returns_service_data(self):
        # NOTE: the harness copies the script queue at make_agent() time, so
        # every scripted selection must be queued BEFORE construction.
        self.mock_llm_chooses("get_findings_posture", "")
        agent = self.make_agent(PostureAgent)
        with patch(f"{_SERVICE}.findings_posture", return_value=_fake_findings()) as fn:
            result = agent.agent_executor.invoke({"input": "what findings are open?"})

        self.assert_tool_called("get_findings_posture")
        fn.assert_called_once_with(agent.workspace_id, window_days=7)
        payload = json.loads(result["output"])
        self.assertEqual(payload["open_findings"]["total"], 3)
        self.assertEqual(payload["needs_human_backlog"]["count"], 1)

    def test_get_findings_posture_honours_window_days(self):
        self.mock_llm_chooses("get_findings_posture", '{"window_days": 30}')
        agent = self.make_agent(PostureAgent)
        with patch(f"{_SERVICE}.findings_posture", return_value=_fake_findings(window_days=30)) as fn:
            agent.agent_executor.invoke({"input": "last 30 days"})
        fn.assert_called_once_with(agent.workspace_id, window_days=30)

    def test_get_response_kpis_returns_bands(self):
        self.mock_llm_chooses("get_response_kpis", "")
        agent = self.make_agent(PostureAgent)
        with patch(f"{_SERVICE}.response_kpis", return_value=_fake_kpis()):
            result = agent.agent_executor.invoke({"input": "are we within band?"})

        payload = json.loads(result["output"])
        self.assertEqual(payload["triage_latency_by_severity"]["critical"]["band_hours"], 1.0)
        self.assertEqual(payload["benchmark_source"], "Prophet Security SOC metrics benchmarks")

    def test_get_fleet_health_returns_service_data(self):
        self.mock_llm_chooses("get_fleet_health", "")
        agent = self.make_agent(PostureAgent)
        with patch(f"{_SERVICE}.fleet_health", return_value=_fake_fleet()):
            result = agent.agent_executor.invoke({"input": "fleet health"})

        payload = json.loads(result["output"])
        self.assertEqual(payload["deep_runs"]["success_rate"], 0.75)
        self.assertEqual(payload["cost"]["total_cost_usd"], 0.42)

    def test_get_forward_outlook_returns_service_data(self):
        self.mock_llm_chooses("get_forward_outlook", "")
        agent = self.make_agent(PostureAgent)
        with patch(f"{_SERVICE}.forward_outlook", return_value=_fake_outlook()):
            result = agent.agent_executor.invoke({"input": "trend?"})

        payload = json.loads(result["output"])
        self.assertEqual(payload["findings_created"]["direction"], "rising")

    def test_tool_failure_degrades_to_message_not_raise(self):
        self.mock_llm_chooses("get_findings_posture", "")
        agent = self.make_agent(PostureAgent)
        with patch(f"{_SERVICE}.findings_posture", side_effect=RuntimeError("db down")):
            result = agent.agent_executor.invoke({"input": "posture?"})

        self.assertIn("Could not compute findings posture", result["output"])


class PostureReportPersonaTests(AgentTestCase):
    """Persona lensing runs through the REAL compose function — only the four
    ORM collectors are mocked — so these pin the actual framing contract."""

    def _patched_collectors(self):
        return (
            patch(f"{_SERVICE}.findings_posture", return_value=_fake_findings()),
            patch(f"{_SERVICE}.response_kpis", return_value=_fake_kpis()),
            patch(f"{_SERVICE}.fleet_health", return_value=_fake_fleet()),
            patch(f"{_SERVICE}.forward_outlook", return_value=_fake_outlook()),
        )

    def _report(self, agent, persona_input):
        result = agent.get_posture_report(persona_input)
        return json.loads(result)

    def test_engineer_report_has_drilldown_with_finding_ids(self):
        agent = self.make_agent(PostureAgent)
        p1, p2, p3, p4 = self._patched_collectors()
        with p1, p2, p3, p4:
            report = self._report(agent, '{"persona": "engineer"}')

        self.assertEqual(report["persona"], "engineer")
        self.assertIn("findings_posture", report)
        self.assertIn("task-1", report["findings_posture"]["open_findings"]["sample_task_ids"])
        self.assertIn("ctem_mapping", report)

    def test_executive_report_is_nacd_shaped_without_ids(self):
        agent = self.make_agent(PostureAgent)
        p1, p2, p3, p4 = self._patched_collectors()
        with p1, p2, p3, p4:
            report = self._report(agent, '{"persona": "executive"}')

        self.assertEqual(report["persona"], "executive")
        self.assertEqual(
            set(report["nacd_summary"]),
            {"threat_environment", "financial", "maturity", "forward_looking"},
        )
        self.assertNotIn("task-1", json.dumps(report))

    def test_same_facts_under_both_lenses(self):
        agent = self.make_agent(PostureAgent)
        p1, p2, p3, p4 = self._patched_collectors()
        with p1, p2, p3, p4:
            engineer = self._report(agent, "engineer")
            executive = self._report(agent, "executive")

        self.assertEqual(
            executive["nacd_summary"]["threat_environment"]["open_findings_total"],
            engineer["findings_posture"]["open_findings"]["total"],
        )
        self.assertEqual(
            executive["nacd_summary"]["financial"]["total_cost_usd_window"],
            engineer["fleet_health"]["cost"]["total_cost_usd"],
        )

    def test_unknown_persona_rejected_with_options(self):
        agent = self.make_agent(PostureAgent)
        result = agent.get_posture_report('{"persona": "hacker"}')
        self.assertIn("Unknown persona", result)
        self.assertIn("engineer", result)
        self.assertIn("executive", result)


class PostureAgentPromptTests(AgentTestCase):
    def test_system_prompt_carries_honesty_and_ctem_rules(self):
        agent = self.make_agent(PostureAgent)
        prompt = agent._build_system_message()

        self.assertIn("NEVER invent a composite 'posture score'", prompt)
        self.assertIn("Answer ONLY from tool output", prompt)
        self.assertIn("Discovery", prompt)
        self.assertIn("Mobilization", prompt)
        self.assertIn("no_data", prompt)
        self.assertIn("median", prompt.lower())
