"""ReportAgent tests (AgentTestCase harness — no real LLM).

Pins the agent's registration + alias contract, that both tools are registered
with the right risk tiers, and the load-bearing grounding property: a finding
NOT in the input to narrate_report_sections never appears in the output. The
narrative path uses the report context's real deterministic verifier via a
fake LLM, so the grounding assertion is honest.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from components.agents.infrastructure.adapters.langchain.agents.report_agent import ReportAgent
from components.agents.tests.agent_test_case import AgentTestCase


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLlm:
    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, prompt, **kwargs):
        return _Resp(self._responses.pop(0) if self._responses else "")


class ReportAgentTests(AgentTestCase):
    def test_registered_under_canonical_name_and_aliases(self):
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        for name in ("report_agent", "report", "reporting", "pentest_report", "security_report"):
            self.assertIs(AgentRegistry.get_agent_class(name), ReportAgent)

    def test_both_tools_registered_with_expected_risk(self):
        from components.agents.application.policies.tool_risk import ToolRisk, normalize_risk

        agent = self.make_agent(ReportAgent)
        by_name = {t.name: t for t in agent.tools}
        self.assertIn("generate_pentest_report", by_name)
        self.assertIn("narrate_report_sections", by_name)
        # generate is a reversible write; narrate is read-only.
        gen_meta = ReportAgent.generate_pentest_report._agent_tool_meta
        nar_meta = ReportAgent.narrate_report_sections._agent_tool_meta
        self.assertEqual(normalize_risk(gen_meta["risk"]), ToolRisk.REVERSIBLE_WRITE)
        self.assertEqual(normalize_risk(nar_meta["risk"]), ToolRisk.READ)

    def test_narrate_is_grounded_finding_not_in_input_never_appears(self):
        agent = self.make_agent(ReportAgent)
        # The LLM tries to invent "Finding Z" and a bogus count; the grounded
        # verifier flags the number, but the invented finding text is never fed
        # to it from the input either way — assert it is absent from the output.
        fake = _FakeLlm(
            [
                "1 finding was identified: 1 High on auth-svc.",
                "The finding is a log anomaly.",
            ]
        )
        with (
            patch(
                "components.report.application.providers.report_provider.ReportProvider.narrative"
            ) as narrative_provider,
            patch(
                "components.report.application.providers.report_provider.ReportProvider.workspace_identity"
            ) as identity_provider,
        ):
            from components.agents.domain.services.faithfulness_verifier import FaithfulnessVerifier
            from components.report.infrastructure.adapters.grounded_report_narrative_adapter import (
                GroundedReportNarrativeAdapter,
            )

            narrative_provider.return_value = GroundedReportNarrativeAdapter(
                llm_port=fake, verifier=FaithfulnessVerifier()
            )

            class _Ident:
                def get(self, *, workspace_id):
                    from components.report.application.ports.workspace_identity_port import (
                        WorkspaceIdentity,
                    )

                    return WorkspaceIdentity(workspace_id=workspace_id, name="Acme SOC", logo_url="")

            identity_provider.return_value = _Ident()

            out = agent.narrate_report_sections(
                json.dumps(
                    {
                        "findings": [
                            {
                                "title": "Auth failures on auth-svc",
                                "severity": "high",
                                "category": "Log Anomaly",
                                "affected_asset": "auth-svc",
                            }
                        ]
                    }
                )
            )
        payload = json.loads(out)
        # The one supplied finding's asset is present; an invented finding is not.
        assert "auth-svc" in json.dumps(payload)
        assert "Finding Z" not in json.dumps(payload)
        assert "unsupported_figures" in payload

    def test_narrate_requires_findings(self):
        agent = self.make_agent(ReportAgent)
        out = agent.narrate_report_sections("{}")
        assert "findings" in out.lower()

    def test_generate_creates_and_enqueues(self):
        agent = self.make_agent(ReportAgent)
        with (
            patch("components.report.application.providers.report_provider.ReportProvider.repository") as repo_provider,
            patch("components.report.workers.tasks.generate_report.delay") as delay,
        ):
            repo = repo_provider.return_value
            repo.create.return_value = {"id": "rep-1", "status": "draft"}
            out = agent.generate_pentest_report(json.dumps({"title": "Q3 Pentest"}))
        payload = json.loads(out)
        assert payload["report_id"] == "rep-1"
        assert payload["status"] == "draft"
        repo.create.assert_called_once()
        delay.assert_called_once()
