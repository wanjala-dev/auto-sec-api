"""The setting reaches the tool gate (ADR 0035 D1/D9).

This is the file that decides whether the mode switch is real. Everything else
— the field, the endpoint, the audit, the HUD control — is scaffolding around
one question: does flipping the workspace to MANUAL actually stop a write from
running?

This repo has shipped the alternative more than once. A card that claimed
"nothing has been graded" for a workspace it never queried; a verifier that
reported PASS for output that did not exist; eight tool names in the risk map
naming tools this fork had deleted. Each looked like it worked. So the tests
here call the wrapper ``_risk_gated`` returns and assert on whether the tool
BODY ran, not on what any intermediate layer reports.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.infrastructure.adapters.langchain.base import _risk_gated
from components.workspace.application.providers.workspace_autonomy_provider import (
    WorkspaceAutonomyProvider,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class _Agent:
    """The attributes ``_risk_gated`` reads off a promoted-tool agent."""

    def __init__(self, workspace_id, user_id=None, config=None):
        self.workspace_id = str(workspace_id)
        self.user_id = str(user_id) if user_id else None
        self.config = config or {}


def _set_mode(workspace, mode):
    WorkspaceAutonomyProvider.build_set_workspace_autonomy_mode_use_case().execute(
        workspace_id=str(workspace.id), mode=mode, actor=None, reason="test"
    )


def _gated(agent, risk, name="record_finding"):
    """A tool that records whether its body ran, wrapped by the real gate."""
    calls = []

    def tool_body(*_args, **_kwargs):
        calls.append(True)
        return "the tool ran"

    wrapper = _risk_gated(tool_body, name, risk, agent)
    return wrapper, calls


class TestManualHoldsWrites:
    def test_a_reversible_write_body_never_runs(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        _set_mode(workspace, "manual")
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.REVERSIBLE_WRITE)

        result = wrapper("payload")

        assert calls == [], "the tool body ran despite MANUAL mode"
        assert "MANUAL" in str(result)

    def test_an_irreversible_action_body_never_runs(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        _set_mode(workspace, "manual")
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.IRREVERSIBLE, name="open_draft_pr")

        wrapper("payload")

        assert calls == []

    def test_an_approval_on_the_run_does_not_unlock_it(self, workspace_factory, user_factory):
        """MANUAL is a standing statement about the workspace. A run must not be
        able to answer its way past it."""
        workspace = workspace_factory()
        _set_mode(workspace, "manual")
        agent = _Agent(workspace.id, user_factory().id, config={"approval_granted": True})
        wrapper, calls = _gated(agent, ToolRisk.REVERSIBLE_WRITE)

        wrapper("payload")

        assert calls == []

    def test_reads_still_run(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        _set_mode(workspace, "manual")
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.READ, name="list_findings")

        assert wrapper("payload") == "the tool ran"
        assert calls == [True]


class TestAssistIsUnchanged:
    def test_a_reversible_write_runs(self, workspace_factory, user_factory):
        """The default. If this ever failed, deploying the field would have
        broken every existing customer's agent."""
        workspace = workspace_factory()
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.REVERSIBLE_WRITE)

        assert wrapper("payload") == "the tool ran"
        assert calls == [True]

    def test_an_irreversible_action_still_needs_approval(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        _set_mode(workspace, "assist")
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.IRREVERSIBLE, name="open_draft_pr")

        result = wrapper("payload")

        assert calls == []
        assert "approval" in str(result).lower()

    def test_an_approved_irreversible_action_runs(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        _set_mode(workspace, "assist")
        agent = _Agent(workspace.id, user_factory().id, config={"approval_granted": True})
        wrapper, calls = _gated(agent, ToolRisk.IRREVERSIBLE, name="open_draft_pr")

        wrapper("payload")

        assert calls == [True]


class TestAutonomousDoesNotWidenTheCeiling:
    def test_selecting_autonomous_does_not_unlock_irreversible_actions(self, workspace_factory, user_factory):
        """D3, asserted at the gate rather than only in the policy unit test.
        This is the one a customer's security review will ask about: does the
        most permissive dropdown position let the AI do irreversible things?"""
        workspace = workspace_factory()
        _set_mode(workspace, "autonomous")
        agent = _Agent(workspace.id, user_factory().id, config={"approval_granted": True})
        wrapper, calls = _gated(agent, ToolRisk.IRREVERSIBLE, name="open_draft_pr")

        wrapper("payload")

        assert calls == [True], (
            "a human-initiated run in an AUTONOMOUS workspace is still ASSIST — "
            "the dial describes who starts runs, not what they may do"
        )


class TestThePolicyIsResolvedOncePerRun:
    def test_changing_the_setting_mid_run_does_not_change_the_rules(self, workspace_factory, user_factory):
        """D1. A deep run executes for minutes; an operator toggling the setting
        must not change what work already in flight is allowed to do. The run
        finishes under the policy it started with."""
        workspace = workspace_factory()
        agent = _Agent(workspace.id, user_factory().id)
        wrapper, calls = _gated(agent, ToolRisk.REVERSIBLE_WRITE)

        wrapper("first")  # resolves ASSIST and caches it on the agent
        _set_mode(workspace, "manual")
        wrapper("second")

        assert calls == [True, True], "the second call was gated by a policy the run did not start under"

    def test_a_run_started_after_the_change_gets_the_new_policy(self, workspace_factory, user_factory):
        """The other half — carrying the policy must not mean ignoring it. A new
        agent instance IS a new run."""
        workspace = workspace_factory()
        _set_mode(workspace, "manual")
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.REVERSIBLE_WRITE)

        wrapper("payload")

        assert calls == []


class TestAnUnreadableSettingFailsClosed:
    def test_a_failed_read_holds_writes_rather_than_defaulting_to_assist(
        self, workspace_factory, user_factory, monkeypatch
    ):
        """The branch nothing exercises in normal operation, which is why it is
        the one that rots. Its failure mode is failing OPEN on the control that
        answers "may the AI change things in my account"."""
        import components.agents.infrastructure.adapters.workspace_autonomy_adapter as adapter_module

        def _explode(self, *, workspace_id):
            raise RuntimeError("settings read failed")

        monkeypatch.setattr(adapter_module.WorkspaceAutonomyAdapter, "get_mode", _explode)

        workspace = workspace_factory()
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.REVERSIBLE_WRITE)

        result = wrapper("payload")

        assert calls == []
        assert "could not be read" in str(result)

    def test_reads_survive_a_failed_settings_read(self, workspace_factory, user_factory, monkeypatch):
        """Otherwise a transient blip on one row would turn every agent in the
        product into a dead one."""
        import components.agents.infrastructure.adapters.workspace_autonomy_adapter as adapter_module

        def _explode(self, *, workspace_id):
            raise RuntimeError("settings read failed")

        monkeypatch.setattr(adapter_module.WorkspaceAutonomyAdapter, "get_mode", _explode)

        workspace = workspace_factory()
        wrapper, calls = _gated(_Agent(workspace.id, user_factory().id), ToolRisk.READ, name="list_findings")

        wrapper("payload")

        assert calls == [True]


class TestTheEvaluationGateStillWinsFirst:
    def test_an_eval_run_refuses_writes_whatever_the_workspace_mode_says(self, workspace_factory, user_factory):
        """ADR 0033 D5 is stricter than any workspace setting, and it must not
        become reachable-past by putting the workspace on AUTONOMOUS."""
        workspace = workspace_factory()
        _set_mode(workspace, "autonomous")
        agent = _Agent(workspace.id, user_factory().id, config={"execution_mode": "evaluation"})
        wrapper, calls = _gated(agent, ToolRisk.REVERSIBLE_WRITE)

        result = wrapper("payload")

        assert calls == []
        assert "Evaluation runs" in str(result)
