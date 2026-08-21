"""An evaluation run must not be able to change anything (ADR 0033 D5).

Evaluating the triage agent means running an agent that can, in normal
operation, open draft PRs on a customer's repository, write findings and move
board cards. Every other invariant in the evaluation work is about honest
numbers; this one is about not damaging the thing being measured. Getting it
wrong is an incident, not a bad answer.

The design turns on one asymmetry. ``resolve_tool_risk`` returns ``read`` for
BOTH a tool declared read and a tool nobody classified. That default is correct
for the autonomy cap — assume least privilege — and exactly backwards here: a
tool nobody classified is a tool nobody has checked. So evaluation fails
CLOSED, and the undeclared case gets its own test rather than riding along with
the write case, because it is the one a reasonable implementation gets wrong.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_risk import (
    EVALUATION_EXECUTION_MODE,
    ToolRisk,
    evaluation_may_execute,
    evaluation_refusal,
    is_risk_declared,
    tool_risk_refusal,
)

pytestmark = [pytest.mark.unit]


class TestOnlyDeclaredReadsRun:
    def test_a_declared_read_tool_executes(self):
        assert evaluation_may_execute("list_findings", ToolRisk.READ) is True
        assert evaluation_refusal("list_findings", ToolRisk.READ) is None

    def test_a_reversible_write_is_refused(self):
        refusal = evaluation_refusal("persist_finding_as_task", ToolRisk.REVERSIBLE_WRITE)

        assert refusal is not None
        assert "read-only" in refusal

    def test_an_irreversible_tool_is_refused(self):
        refusal = evaluation_refusal("open_draft_pr", ToolRisk.IRREVERSIBLE)

        assert refusal is not None
        assert "read-only" in refusal

    def test_the_refusal_tells_the_agent_what_to_do_instead(self):
        """A bare denial makes the model retry. Naming the alternative lets the
        run continue and still produce something gradeable."""
        refusal = evaluation_refusal("open_draft_pr", ToolRisk.IRREVERSIBLE)

        assert "WOULD have done" in refusal


class TestFailsClosedOnUndeclaredTools:
    """The case a reasonable implementation gets wrong."""

    def test_an_undeclared_tool_is_refused(self):
        assert is_risk_declared("brand_new_tool", None) is False
        assert evaluation_may_execute("brand_new_tool", None) is False
        assert evaluation_refusal("brand_new_tool", None) is not None

    def test_undeclared_is_refused_even_though_it_resolves_to_read(self):
        """The trap, stated explicitly.

        ``resolve_tool_risk`` says READ for an undeclared tool, so a gate built
        on the resolved tier alone would let every unclassified tool run inside
        an eval — including one that writes.
        """
        from components.agents.application.policies.tool_risk import resolve_tool_risk

        assert resolve_tool_risk("brand_new_tool", None) == ToolRisk.READ
        assert evaluation_may_execute("brand_new_tool", None) is False

    def test_the_undeclared_refusal_names_the_fix(self):
        refusal = evaluation_refusal("brand_new_tool", None)

        assert "no risk tier" in refusal
        assert "Declare its tier" in refusal

    def test_a_garbage_tier_is_treated_as_undeclared(self):
        assert is_risk_declared("weird_tool", "totally-made-up") is False
        assert evaluation_refusal("weird_tool", "totally-made-up") is not None

    def test_an_unnamed_tool_is_refused(self):
        assert evaluation_may_execute(None, None) is False
        assert evaluation_refusal(None, None) is not None


class TestTheOtherGatesAreUnchanged:
    """D5 adds a gate; it must not quietly relax the two that already exist."""

    def test_autonomy_cap_still_denies_irreversible(self):
        refusal = tool_risk_refusal(ToolRisk.IRREVERSIBLE, is_autonomous=True, approval_granted=True)

        assert refusal is not None
        assert "Autonomous" in refusal

    def test_approval_gate_still_applies(self):
        refusal = tool_risk_refusal(ToolRisk.IRREVERSIBLE, is_autonomous=False, approval_granted=False)

        assert refusal is not None
        assert "human approval" in refusal

    def test_a_normal_run_still_executes_reversible_writes(self):
        """Evaluation is stricter than normal operation, not a replacement for
        it. If this fails, D5 has broken the product it protects."""
        assert tool_risk_refusal(ToolRisk.REVERSIBLE_WRITE, is_autonomous=True, approval_granted=False) is None


class TestTheModeStringIsShared:
    def test_runner_and_enforcer_agree_on_one_constant(self):
        """A literal in two files is a drift waiting to happen — and a drift
        here means the gate silently stops applying."""
        assert EVALUATION_EXECUTION_MODE == "evaluation"

    def test_the_gate_is_wired_to_that_constant(self):
        """Reads the enforcement site rather than trusting that it imports it,
        because an unused import would still pass a smoke test."""
        from pathlib import Path

        import components.agents.infrastructure.adapters.langchain.base as base_module

        source = Path(base_module.__file__).read_text()

        assert "EVALUATION_EXECUTION_MODE" in source
        assert "evaluation_refusal" in source
