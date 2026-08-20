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
        # The registry classifies ``delete_task`` reversible_write; an explicit
        # decorator tier overrides it, so new tools own their classification.
        assert resolve_tool_risk("delete_task", ToolRisk.IRREVERSIBLE) == ToolRisk.IRREVERSIBLE
        assert resolve_tool_risk("delete_task", ToolRisk.READ) == ToolRisk.READ

    def test_registry_classifies_the_live_soft_deletes_reversible(self):
        # These two are the whole map since ADR 0031 Phase 0 removed the eight
        # nonprofit names this fork deleted. No tool is registry-classified
        # ``irreversible`` any more — the live irreversible tool
        # (``open_draft_pr``) declares its tier on the ``@tool`` decorator, which
        # is where every new tool declares it.
        assert resolve_tool_risk("delete_task") == ToolRisk.REVERSIBLE_WRITE
        assert resolve_tool_risk("delete_project_milestone") == ToolRisk.REVERSIBLE_WRITE

    def test_unlisted_tool_defaults_to_read(self):
        assert resolve_tool_risk("list_open_findings") == ToolRisk.READ
