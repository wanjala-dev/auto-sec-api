"""What a model switch costs, stated BEFORE the switch (ADR 0032 D7.3).

The feature Henry asked for — "let the workspace admin change models" — has a
consequence the codebase had already decided once and never surfaced: evidence
gathered under one model does not transfer to another. A switch therefore
silently revokes measured trust, and *"a switch that quietly revokes measured
trust is the same class of defect as a report that reads clean because nothing
was scanned"* (ADR 0032 D7).

This query composes the sentence the switch UI must show. It is deliberately
NOT a gate: switching stays the operator's call. It only refuses to let the
cost be discovered afterwards.

Framework-free, per the application-layer rule — it talks to a port.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.agents.application.ports.measured_evidence_port import (
    MeasuredEvidencePort,
    ModelSwitchImpactView,
)

#: The anti-thrash note (D7.6). A workspace that switches weekly never
#: accumulates measured trust, because every switch restarts the count. Stated
#: in the copy rather than left for the admin to infer.
ANTI_THRASH_NOTE = (
    "Measurement restarts from zero after every switch, so a workspace that "
    "changes model often never accumulates measured trust."
)


@dataclass(frozen=True)
class ModelSwitchCostView:
    """The impact plus the operator-facing sentence, ready to render."""

    impact: ModelSwitchImpactView
    headline: str
    detail: str
    anti_thrash_note: str

    def as_dict(self) -> dict:
        return {
            "current_model": self.impact.current_model,
            "candidate_model": self.impact.candidate_model,
            "is_noop": self.impact.is_noop,
            "measured_rules": self.impact.measured_rules,
            "downgraded_count": len(self.impact.downgraded),
            "unchanged_count": self.impact.unchanged,
            "min_trials_to_remeasure": self.impact.min_trials_to_remeasure,
            "downgraded": [
                {
                    "rule_id": rule.rule_id,
                    "from_tier": rule.from_tier,
                    "to_tier": rule.to_tier,
                    "trials": rule.trials,
                    "passes": rule.passes,
                    "reason": rule.reason,
                }
                for rule in self.impact.downgraded
            ],
            "headline": self.headline,
            "detail": self.detail,
            "anti_thrash_note": self.anti_thrash_note,
        }


@dataclass
class FetchModelSwitchCostQuery:
    """Resolve + phrase the measured-evidence cost of a candidate model."""

    port: MeasuredEvidencePort

    def execute(self, *, current_model: str, candidate_model: str) -> ModelSwitchCostView:
        impact = self.port.model_switch_impact(
            current_model=current_model,
            candidate_model=candidate_model,
        )

        if impact.is_noop:
            return ModelSwitchCostView(
                impact=impact,
                headline="No change — this is already the workspace's model.",
                detail="",
                anti_thrash_note="",
            )

        lost = len(impact.downgraded)
        if lost:
            headline = (
                f"Switching to {impact.candidate_model or 'this model'} will drop "
                f"{lost} of {impact.measured_rules} measured fix rules to 'unproven' "
                "and reset agent measurement for this workspace."
            )
        elif impact.measured_rules == 0:
            # Absence is a distinct state (D4): "nothing to lose" because
            # nothing was ever measured is NOT the same as "safe to switch".
            headline = (
                "Nothing has been measured on the current model, so this switch "
                "costs no measured trust — there is none to lose."
            )
        else:
            headline = f"None of the {impact.measured_rules} measured fix rules change tier under this model."

        detail = (
            f"Measurements do not transfer between models. Re-earning a tier "
            f"requires at least {impact.min_trials_to_remeasure} trials per rule "
            "on the new model."
        )
        return ModelSwitchCostView(
            impact=impact,
            headline=headline,
            detail=detail,
            anti_thrash_note=ANTI_THRASH_NOTE,
        )
