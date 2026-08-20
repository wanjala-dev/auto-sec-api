"""Adapter: resolve the measured-evidence cost of a model switch.

Implements :class:`MeasuredEvidencePort` over the committed SAST fix-confidence
corpus (``code_security/rules/remediation/fix_confidence.yaml``). It calls
``confidence_for`` twice per rule — once naming the current model, once naming
the candidate — and diffs the resulting tiers. Nothing is re-derived here: the
tier ladder, the trials floor and the expiry are ``fix_confidence``'s, which is
the point (ADR 0032 D3 — one statistic, one ladder).

Cross-context by design and allowed: an adapter may read another context's
DOMAIN (``components.<other>.domain.*``). What must never happen is the agents
APPLICATION layer importing it — hence the port.
"""

from __future__ import annotations

import logging

from components.agents.application.ports.measured_evidence_port import (
    MeasuredEvidencePort,
    ModelSwitchImpactView,
    RuleEvidenceImpactView,
)

logger = logging.getLogger(__name__)

#: Tier ordering, worst → best. A move DOWN this list is a downgrade.
_TIER_RANK = {"unproven": 0, "measured_weak": 1, "proven": 2}


class FixConfidenceEvidenceAdapter(MeasuredEvidencePort):
    """Reads the SAST fix-confidence corpus. No DB, no network."""

    def model_switch_impact(self, *, current_model: str, candidate_model: str) -> ModelSwitchImpactView:
        from components.code_security.domain.fix_confidence import (
            AUTOFIX_MIN_TRIALS,
            TIER_UNPROVEN,
            confidence_for,
            measured_rules,
        )

        current_model = str(current_model or "").strip()
        candidate_model = str(candidate_model or "").strip()

        try:
            rules = measured_rules()
        except Exception:
            # A malformed corpus is loud in its own module and fatal for the
            # SAST path; for a PREVIEW it must not 500 the settings screen.
            # Report zero measured rules — which understates nothing, because
            # an unreadable corpus means no rule is proven anyway.
            logger.exception("fix confidence corpus unreadable — reporting no measured evidence")
            rules = {}

        downgraded: list[RuleEvidenceImpactView] = []
        unchanged = 0
        for rule_id in sorted(rules):
            try:
                before = confidence_for(rule_id, model=current_model)
                after = confidence_for(rule_id, model=candidate_model)
            except Exception:
                logger.exception("fix confidence resolution failed rule_id=%s", rule_id)
                # Fail closed: unresolvable means we cannot promise the tier
                # survives, so it counts as lost.
                downgraded.append(
                    RuleEvidenceImpactView(
                        rule_id=rule_id,
                        from_tier=TIER_UNPROVEN,
                        to_tier=TIER_UNPROVEN,
                        trials=0,
                        passes=0,
                        reason="this rule's confidence could not be resolved — treated as lost",
                    )
                )
                continue

            if _TIER_RANK.get(after.tier, 0) < _TIER_RANK.get(before.tier, 0):
                downgraded.append(
                    RuleEvidenceImpactView(
                        rule_id=rule_id,
                        from_tier=before.tier,
                        to_tier=after.tier,
                        trials=before.trials,
                        passes=before.passes,
                        reason=after.reason,
                    )
                )
            else:
                unchanged += 1

        return ModelSwitchImpactView(
            current_model=current_model,
            candidate_model=candidate_model,
            measured_rules=len(rules),
            downgraded=tuple(downgraded),
            unchanged=unchanged,
            min_trials_to_remeasure=AUTOFIX_MIN_TRIALS,
            is_noop=bool(current_model) and current_model == candidate_model,
        )
