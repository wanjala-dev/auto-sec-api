"""What a mode permits (ADR 0035 D1/D2/D3).

``autonomy_mode.py`` answers *what autonomy was this run under*. This answers
*and therefore what may it do* — the enforcement half.

**One object, resolved once.** D1 makes the mode a policy object resolved at run
start and carried on the run, not a flag consulted per call. The difference is
not stylistic: a deep run can execute for many minutes, and if the rules were
re-read per tool call, an operator toggling the setting mid-run would change the
rules underneath work already in flight. A run finishes under the policy it
started with.

**ASSIST and AUTONOMOUS delegate to the existing gate, deliberately.** Their
decisions come from ``tool_risk_refusal`` — the function that has been enforcing
SEE-201/SEE-203 all along — so this change cannot alter today's behaviour for
today's modes. The new branch is MANUAL. Rewriting the existing rules here would
have meant two descriptions of one policy, and D9 exists because this codebase
already knows what unenforced duplication becomes: eight tool names sat in the
risk map naming tools this fork had deleted, for months, because nothing checked.

**AUTONOMOUS does not widen anything (D3).** It is not a step up the ladder from
ASSIST in what it permits — it is the same ceiling with nobody waiting. If the
mode selector unlocked irreversible actions, one dropdown would separate a
customer from unattended destructive writes, and it would be the most dangerous
control in the product.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from components.agents.application.policies.tool_risk import (
    ToolRisk,
    normalize_risk,
    tool_risk_refusal,
)
from components.agents.domain.value_objects.autonomy_mode import AutonomyMode


class ToolDecision(Enum):
    """What happens to one tool call under one mode."""

    #: The tool body runs.
    EXECUTE = "execute"

    #: MANUAL. The write does not run; the agent reports what it would have
    #: done. Not a failure — it is the mode working.
    HOLD = "hold"

    #: An irreversible action a human could still approve for this run.
    REQUIRE_APPROVAL = "require_approval"

    #: Refused outright, with no approval path from here.
    DENY = "deny"

    @property
    def executes(self) -> bool:
        return self is ToolDecision.EXECUTE


@dataclass(frozen=True)
class AutonomyPolicy:
    """The rules one run executes under. Build once per run; never mutate."""

    mode: AutonomyMode

    @classmethod
    def for_mode(cls, mode: AutonomyMode) -> AutonomyPolicy:
        return cls(mode=mode)

    def decide(self, risk: str | None, *, approval_granted: bool) -> ToolDecision:
        """Whether a tool of *risk* may run under this policy."""

        normalized = normalize_risk(risk)

        if self.mode in (AutonomyMode.MANUAL, AutonomyMode.UNKNOWN):
            # Reads still execute: MANUAL is "look but do not touch", not
            # "sit down". An agent that cannot read cannot advise, and a mode
            # whose only behaviour is refusal teaches operators to leave it off.
            # A read changes nothing, so there is nothing to hold.
            if normalized == ToolRisk.READ:
                return ToolDecision.EXECUTE
            # UNKNOWN lands here deliberately. If we could not determine what
            # this customer permitted, the answer to "may I change their
            # account?" is no. Defaulting an unreadable setting to ASSIST would
            # fail open on the one control that exists to prevent exactly that.
            return ToolDecision.HOLD

        # ASSIST / AUTONOMOUS / EVALUATION — the gate that already enforces
        # SEE-201 and SEE-203, unchanged.
        is_autonomous = self.mode is AutonomyMode.AUTONOMOUS
        if tool_risk_refusal(normalized, is_autonomous=is_autonomous, approval_granted=approval_granted) is None:
            return ToolDecision.EXECUTE
        return ToolDecision.DENY if is_autonomous else ToolDecision.REQUIRE_APPROVAL

    def refusal(self, tool_name: str | None, risk: str | None, *, approval_granted: bool) -> str | None:
        """The message the agent sees, or ``None`` when the tool may run.

        Worded per decision because each one needs a different response from
        whoever reads it. A HOLD asks the agent to write up the action; a
        REQUIRE_APPROVAL asks the user to confirm; a DENY tells the agent to
        stop asking and raise a finding instead.
        """

        decision = self.decide(risk, approval_granted=approval_granted)
        if decision.executes:
            return None

        if decision is ToolDecision.HOLD:
            # Two causes, two messages. Telling an operator "you are in MANUAL
            # mode" when the truth is "we could not read your setting" would
            # send them to a settings page that already says what they want.
            if self.mode is AutonomyMode.UNKNOWN:
                return (
                    f"This workspace's autonomy setting could not be read, so '{tool_name or 'this tool'}' "
                    "was not run — an unreadable policy is treated as permitting no changes. "
                    "Describe what you would have done, and report that the setting needs checking."
                )
            return (
                f"This workspace is in MANUAL mode, so '{tool_name or 'this tool'}' was not run. "
                "Describe exactly what you would have done — the action, its target, and why — "
                "so a human can carry it out or switch the workspace to ASSIST."
            )

        # The existing wording for the existing decisions, from the one place
        # that has always produced it.
        return tool_risk_refusal(
            risk,
            is_autonomous=self.mode is AutonomyMode.AUTONOMOUS,
            approval_granted=approval_granted,
        )


__all__ = ["AutonomyPolicy", "ToolDecision"]
