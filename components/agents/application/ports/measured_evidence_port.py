"""Port: what measured evidence a model switch would invalidate (ADR 0032 D7).

Switching a workspace's model silently revokes measured trust. That is not a
side effect to be discovered afterwards — it is the cost of the action, and the
operator has to be told BEFORE they take it. ``fix_confidence`` already decided
this once for SAST rules: evidence measured on model X resolves to ``unproven``
the moment you run model Y, with the message *"measurements do not transfer
between models"*. The committed corpus is ``gpt-3.5-turbo``, so a workspace
that switches today drops every measured rule to ``unproven`` — correct, and
currently invisible.

The port exists so the agents context can ASK that question without importing
another context's evidence loader into its application layer. The adapter that
answers it consumes ``code_security.domain.fix_confidence``; the use case that
composes the warning never learns SAST exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleEvidenceImpactView:
    """One measured rule and what the switch would do to its tier."""

    rule_id: str
    from_tier: str
    to_tier: str
    trials: int
    passes: int
    reason: str


@dataclass(frozen=True)
class ModelSwitchImpactView:
    """The measured-evidence cost of moving from one model to another."""

    current_model: str
    candidate_model: str
    #: Rules carrying committed evidence at all — the denominator.
    measured_rules: int
    #: Rules whose tier gets WORSE under the candidate model.
    downgraded: tuple[RuleEvidenceImpactView, ...]
    #: Rules whose tier is unchanged (usually because they were already
    #: ``unproven`` — being told "nothing to lose" is a real answer).
    unchanged: int
    #: Trials needed per rule before a tier can be re-earned.
    min_trials_to_remeasure: int
    #: True when the two models are the same string — no cost, no warning.
    is_noop: bool


class MeasuredEvidencePort(ABC):
    """Read-only. Answers "what does this switch cost in measured trust?"."""

    @abstractmethod
    def model_switch_impact(self, *, current_model: str, candidate_model: str) -> ModelSwitchImpactView:
        """Resolve every measured rule under both models and diff the tiers.

        MUST fail closed: a rule whose tier cannot be resolved under the
        candidate counts as a downgrade, never as retained.
        """
        ...
