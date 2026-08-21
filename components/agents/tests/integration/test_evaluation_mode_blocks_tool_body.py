"""The gate must actually stop the tool BODY, not merely disapprove of it.

``test_evaluation_isolation.py`` proves the policy decides correctly. This
proves the decision is wired to the thing that runs — which is a separate
question, and the one this codebase keeps getting wrong: the sign-off audit
had a correct port, a correct adapter and correct provider wiring, and wrote
nothing, because nobody followed the call through to the end.

So these tests drive ``_risk_gated`` itself and assert on a side effect. A tool
that records it ran is the only witness that cannot be argued with.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_risk import (
    EVALUATION_EXECUTION_MODE,
    ToolRisk,
)
from components.agents.infrastructure.adapters.langchain.base import _risk_gated

pytestmark = [pytest.mark.integration]


class _FakeAgent:
    """Minimal stand-in carrying only what the gate reads."""

    def __init__(self, execution_mode: str | None = None, approval_granted: bool = False):
        self.user_id = None
        self.workspace_id = None
        self.config = {}
        if execution_mode is not None:
            self.config["execution_mode"] = execution_mode
        if approval_granted:
            self.config["approval_granted"] = True


@pytest.fixture
def spy():
    """A tool that leaves a mark when its body executes."""
    calls: list[str] = []

    def _tool(*args, **kwargs):
        calls.append("ran")
        return "side effect happened"

    _tool.calls = calls
    return _tool


def _run(spy, *, tool_name, risk, agent):
    return _risk_gated(spy, tool_name, risk, agent)()


class TestEvaluationModeStopsTheBody:
    def test_a_write_tool_body_never_runs(self, spy):
        agent = _FakeAgent(execution_mode=EVALUATION_EXECUTION_MODE)

        result = _run(spy, tool_name="persist_finding_as_task", risk=ToolRisk.REVERSIBLE_WRITE, agent=agent)

        assert spy.calls == [], "the tool body executed inside an evaluation run"
        assert "read-only" in str(result)

    def test_an_irreversible_tool_body_never_runs(self, spy):
        agent = _FakeAgent(execution_mode=EVALUATION_EXECUTION_MODE)

        _run(spy, tool_name="open_draft_pr", risk=ToolRisk.IRREVERSIBLE, agent=agent)

        assert spy.calls == []

    def test_an_undeclared_tool_body_never_runs(self, spy):
        """Fail-closed, end to end."""
        agent = _FakeAgent(execution_mode=EVALUATION_EXECUTION_MODE)

        result = _run(spy, tool_name="brand_new_tool", risk=None, agent=agent)

        assert spy.calls == []
        assert "no risk tier" in str(result)

    def test_approval_cannot_buy_a_write_inside_an_evaluation(self, spy):
        """An eval run is not a privilege question. Even with approval granted
        — which clears the irreversible gate in normal operation — an eval must
        not write, because the objection is to changing the thing being
        measured, not to the caller's authority."""
        agent = _FakeAgent(execution_mode=EVALUATION_EXECUTION_MODE, approval_granted=True)

        _run(spy, tool_name="open_draft_pr", risk=ToolRisk.IRREVERSIBLE, agent=agent)

        assert spy.calls == []

    def test_a_declared_read_tool_body_does_run(self, spy):
        """The other direction. A gate that blocks everything would pass every
        test above and make evaluation useless."""
        agent = _FakeAgent(execution_mode=EVALUATION_EXECUTION_MODE)

        result = _run(spy, tool_name="list_findings", risk=ToolRisk.READ, agent=agent)

        assert spy.calls == ["ran"]
        assert result == "side effect happened"

    def test_the_mode_is_matched_case_and_space_insensitively(self, spy):
        agent = _FakeAgent(execution_mode="  Evaluation  ")

        _run(spy, tool_name="persist_finding_as_task", risk=ToolRisk.REVERSIBLE_WRITE, agent=agent)

        assert spy.calls == []


class TestNormalRunsAreUnaffected:
    def test_a_normal_run_still_executes_a_reversible_write(self, spy):
        """D5 must not quietly turn the product read-only."""
        agent = _FakeAgent()

        _run(spy, tool_name="persist_finding_as_task", risk=ToolRisk.REVERSIBLE_WRITE, agent=agent)

        assert spy.calls == ["ran"]

    def test_a_normal_run_still_executes_an_undeclared_tool(self, spy):
        """Undeclared means refused in EVAL only. Applying fail-closed
        everywhere would break every tool that predates the contract."""
        agent = _FakeAgent()

        _run(spy, tool_name="brand_new_tool", risk=None, agent=agent)

        assert spy.calls == ["ran"]

    def test_an_unrelated_execution_mode_does_not_trigger_the_gate(self, spy):
        agent = _FakeAgent(execution_mode="interactive")

        _run(spy, tool_name="persist_finding_as_task", risk=ToolRisk.REVERSIBLE_WRITE, agent=agent)

        assert spy.calls == ["ran"]


class TestDegradedAgents:
    def test_an_agent_with_no_config_is_treated_as_a_normal_run(self, spy):
        class _Bare:
            user_id = None
            workspace_id = None

        _run(spy, tool_name="persist_finding_as_task", risk=ToolRisk.REVERSIBLE_WRITE, agent=_Bare())

        assert spy.calls == ["ran"]

    def test_a_none_config_does_not_crash_the_gate(self, spy):
        agent = _FakeAgent()
        agent.config = None

        _run(spy, tool_name="list_findings", risk=ToolRisk.READ, agent=agent)

        assert spy.calls == ["ran"]
