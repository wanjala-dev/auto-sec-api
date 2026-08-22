"""What each mode permits (ADR 0035 D1/D2/D3).

Two properties matter more than the individual rows.

The first is that **ASSIST and AUTONOMOUS behave exactly as they did before this
existed**. Introducing a policy object in front of the only gate that has ever
enforced SEE-201/SEE-203 is the kind of change that quietly relaxes something,
and "nobody's behaviour changes on deploy" is a claim that needs a test rather
than a sentence in an ADR.

The second is that **UNKNOWN holds writes**. It is the branch nothing exercises
in normal operation, which is precisely why it is the one that rots — and its
failure mode is failing open on "may the AI change my account".
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.autonomy_policy import AutonomyPolicy, ToolDecision
from components.agents.application.policies.tool_risk import ToolRisk, tool_risk_refusal
from components.agents.domain.value_objects.autonomy_mode import AutonomyMode

pytestmark = [pytest.mark.unit]

ALL_RISKS = (ToolRisk.READ, ToolRisk.REVERSIBLE_WRITE, ToolRisk.IRREVERSIBLE)


def _policy(mode):
    return AutonomyPolicy.for_mode(mode)


class TestTodaysBehaviourIsUnchanged:
    """The regression guard on introducing the policy object at all."""

    @pytest.mark.parametrize("mode", [AutonomyMode.ASSIST, AutonomyMode.AUTONOMOUS])
    @pytest.mark.parametrize("risk", ALL_RISKS)
    @pytest.mark.parametrize("approved", [True, False])
    def test_it_agrees_with_the_gate_that_predates_it(self, mode, risk, approved):
        executes = _policy(mode).decide(risk, approval_granted=approved).executes
        legacy_allowed = (
            tool_risk_refusal(
                risk,
                is_autonomous=mode is AutonomyMode.AUTONOMOUS,
                approval_granted=approved,
            )
            is None
        )

        assert executes is legacy_allowed

    def test_the_refusal_wording_is_the_gate_s_own(self):
        """Not paraphrased. Operators and prompts have read these strings for
        as long as the gate has existed."""
        policy = _policy(AutonomyMode.ASSIST)

        assert policy.refusal("delete_task", ToolRisk.IRREVERSIBLE, approval_granted=False) == tool_risk_refusal(
            ToolRisk.IRREVERSIBLE, is_autonomous=False, approval_granted=False
        )


class TestAssist:
    def test_reversible_writes_run(self):
        assert _policy(AutonomyMode.ASSIST).decide(ToolRisk.REVERSIBLE_WRITE, approval_granted=False).executes

    def test_irreversible_waits_for_a_human(self):
        assert (
            _policy(AutonomyMode.ASSIST).decide(ToolRisk.IRREVERSIBLE, approval_granted=False)
            is ToolDecision.REQUIRE_APPROVAL
        )

    def test_irreversible_runs_once_approved(self):
        assert _policy(AutonomyMode.ASSIST).decide(ToolRisk.IRREVERSIBLE, approval_granted=True).executes


class TestAutonomousDoesNotWiden:
    """D3 — the decision most likely to be argued with, so it is pinned."""

    def test_irreversible_is_refused_outright_even_with_approval(self):
        """No human is waiting on an unattended run, so an approval flag on one
        is not a human decision — it is a flag. If this ever passed, one
        dropdown would separate a customer from unattended destructive writes."""
        decision = _policy(AutonomyMode.AUTONOMOUS).decide(ToolRisk.IRREVERSIBLE, approval_granted=True)

        assert decision is ToolDecision.DENY

    def test_it_permits_nothing_assist_does_not(self):
        for risk in ALL_RISKS:
            autonomous = _policy(AutonomyMode.AUTONOMOUS).decide(risk, approval_granted=False).executes
            assist = _policy(AutonomyMode.ASSIST).decide(risk, approval_granted=False).executes
            assert not (autonomous and not assist), f"AUTONOMOUS widened {risk}"


class TestManual:
    def test_reads_still_run(self):
        """MANUAL is "look but do not touch", not "sit down". An agent that
        cannot read cannot advise, and a mode that only refuses gets turned
        off."""
        assert _policy(AutonomyMode.MANUAL).decide(ToolRisk.READ, approval_granted=False).executes

    @pytest.mark.parametrize("risk", [ToolRisk.REVERSIBLE_WRITE, ToolRisk.IRREVERSIBLE])
    def test_every_write_is_held(self, risk):
        assert _policy(AutonomyMode.MANUAL).decide(risk, approval_granted=False) is ToolDecision.HOLD

    def test_an_approval_does_not_unlock_a_write(self):
        """MANUAL is a standing instruction about this workspace, not a prompt
        the run can answer its way past."""
        assert (
            _policy(AutonomyMode.MANUAL).decide(ToolRisk.REVERSIBLE_WRITE, approval_granted=True) is ToolDecision.HOLD
        )

    def test_the_message_asks_for_the_proposal_rather_than_just_refusing(self):
        message = _policy(AutonomyMode.MANUAL).refusal("open_draft_pr", ToolRisk.IRREVERSIBLE, approval_granted=False)

        assert "MANUAL" in message
        assert "open_draft_pr" in message
        assert "would have done" in message


class TestUnknownFailsClosed:
    def test_writes_are_held_when_the_setting_could_not_be_read(self):
        """The whole point. "We do not know what you permitted" resolves to
        "then do not change anything"."""
        assert _policy(AutonomyMode.UNKNOWN).decide(ToolRisk.REVERSIBLE_WRITE, approval_granted=False) is (
            ToolDecision.HOLD
        )

    def test_it_never_silently_behaves_like_assist(self):
        for risk in (ToolRisk.REVERSIBLE_WRITE, ToolRisk.IRREVERSIBLE):
            assert not _policy(AutonomyMode.UNKNOWN).decide(risk, approval_granted=True).executes

    def test_reads_still_run(self):
        """A read changes nothing, so there is nothing to hold — and blocking
        reads would turn a transient settings-read blip into a dead agent."""
        assert _policy(AutonomyMode.UNKNOWN).decide(ToolRisk.READ, approval_granted=False).executes

    def test_the_message_names_the_real_cause_not_manual_mode(self):
        """Telling an operator "you are in MANUAL mode" when the truth is "we
        could not read your setting" sends them to a page that already says
        what they want it to say."""
        message = _policy(AutonomyMode.UNKNOWN).refusal(
            "record_finding", ToolRisk.REVERSIBLE_WRITE, approval_granted=False
        )

        assert "could not be read" in message
        assert "MANUAL mode" not in message


class TestUnclassifiedToolsAreNotAFreePass:
    @pytest.mark.parametrize(
        "mode", [AutonomyMode.MANUAL, AutonomyMode.ASSIST, AutonomyMode.AUTONOMOUS, AutonomyMode.UNKNOWN]
    )
    def test_an_unknown_risk_string_is_treated_as_read(self, mode):
        """``normalize_risk`` has always defaulted to ``read``; this pins that
        the policy inherits that rather than inventing a second answer."""
        assert _policy(mode).decide("nonsense-tier", approval_granted=False) == _policy(mode).decide(
            ToolRisk.READ, approval_granted=False
        )
