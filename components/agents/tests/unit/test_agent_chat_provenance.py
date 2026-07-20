"""Provenance extraction for assistant messages.

The chat use case stamps the specialists a plan routed to onto the
persisted message metadata (and the response body) so the HUD can show
"answered by" chips that survive a conversation reload.
"""

from types import SimpleNamespace

from components.agents.application.use_cases.agent_chat_use_case import (
    _extract_plan_agent_types,
)


class TestExtractPlanAgentTypes:
    def test_dict_plan_and_tasks(self):
        state = {
            "plan": {
                "tasks": [
                    {"agent_type": "triage_agent"},
                    {"agent_type": "optimization_agent"},
                ]
            }
        }
        assert _extract_plan_agent_types(state) == [
            "triage_agent",
            "optimization_agent",
        ]

    def test_object_plan_and_tasks(self):
        plan = SimpleNamespace(
            tasks=[
                SimpleNamespace(agent_type="workspace_agent"),
                SimpleNamespace(agent_type="task_agent"),
            ]
        )
        assert _extract_plan_agent_types({"plan": plan}) == [
            "workspace_agent",
            "task_agent",
        ]

    def test_dedupes_and_skips_clarify_and_blanks(self):
        state = {
            "plan": {
                "tasks": [
                    {"agent_type": "triage_agent"},
                    {"agent_type": "triage_agent"},
                    {"agent_type": "clarify"},
                    {"agent_type": ""},
                    {},
                ]
            }
        }
        assert _extract_plan_agent_types(state) == ["triage_agent"]

    def test_failure_safe_on_junk(self):
        assert _extract_plan_agent_types(None) == []
        assert _extract_plan_agent_types({}) == []
        assert _extract_plan_agent_types({"plan": 42}) == []
        assert _extract_plan_agent_types({"plan": {"tasks": "nope"}}) == []
