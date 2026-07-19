"""SEE-203 — per-tool risk tier policy (pure).

Pins the autonomy cap and human-approval gate, and how a tool's tier resolves
(explicit decorator arg > central registry > read default).
"""

from __future__ import annotations

from components.agents.application.policies.tool_risk import (
    ToolRisk,
    autonomous_may_execute,
    normalize_risk,
    requires_human_approval,
    resolve_tool_risk,
    tool_risk_refusal,
)


class TestTierPredicates:
    def test_unknown_tier_normalises_to_read(self):
        assert normalize_risk("bogus") == ToolRisk.READ
        assert normalize_risk(None) == ToolRisk.READ

    def test_autonomous_may_execute_read_and_reversible_only(self):
        assert autonomous_may_execute(ToolRisk.READ) is True
        assert autonomous_may_execute(ToolRisk.REVERSIBLE_WRITE) is True
        assert autonomous_may_execute(ToolRisk.IRREVERSIBLE) is False

    def test_only_irreversible_needs_approval(self):
        assert requires_human_approval(ToolRisk.IRREVERSIBLE) is True
        assert requires_human_approval(ToolRisk.REVERSIBLE_WRITE) is False
        assert requires_human_approval(ToolRisk.READ) is False


class TestRefusal:
    def test_read_always_runs(self):
        assert tool_risk_refusal(ToolRisk.READ, is_autonomous=True, approval_granted=False) is None

    def test_reversible_write_runs_for_autonomous(self):
        assert tool_risk_refusal(ToolRisk.REVERSIBLE_WRITE, is_autonomous=True, approval_granted=False) is None

    def test_irreversible_denied_to_autonomous_even_with_approval(self):
        # The autonomy cap is checked before approval — an autonomous run never
        # self-executes an irreversible action.
        refusal = tool_risk_refusal(ToolRisk.IRREVERSIBLE, is_autonomous=True, approval_granted=True)
        assert refusal is not None
        assert "Autonomous" in refusal

    def test_irreversible_needs_approval_for_interactive(self):
        refusal = tool_risk_refusal(ToolRisk.IRREVERSIBLE, is_autonomous=False, approval_granted=False)
        assert refusal is not None
        assert "approval" in refusal.lower()

    def test_irreversible_runs_for_interactive_with_approval(self):
        assert tool_risk_refusal(ToolRisk.IRREVERSIBLE, is_autonomous=False, approval_granted=True) is None


class TestResolveToolRisk:
    def test_explicit_decorator_arg_wins(self):
        # A tool the registry marks irreversible can be overridden by an explicit
        # decorator tier (new tools own their classification).
        assert resolve_tool_risk("cancel_sponsorship", ToolRisk.READ) == ToolRisk.READ

    def test_registry_classifies_money_tools_irreversible(self):
        assert resolve_tool_risk("manage_sponsorship_payments") == ToolRisk.IRREVERSIBLE
        assert resolve_tool_risk("delete_transaction") == ToolRisk.IRREVERSIBLE

    def test_unlisted_tool_defaults_to_read(self):
        assert resolve_tool_risk("list_recipients") == ToolRisk.READ
