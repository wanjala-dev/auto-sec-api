"""AttackPathRemediationAdvisor — how to break a toxic combination (owned risk logic).

The consumer half of the attack-path pipeline: given a materialised attack-path finding
(its category + entry/target + the typed edges), produce a GROUNDED remediation — one that
names the actual entry, the crown-jewel target, and the concrete way to sever the chain.

Deterministic on purpose (no LLM): the analyzer already computed the toxic path, so the
remediation is a function of the category + the named resources. That makes the suggestion
inherently grounded (it references the finding's own evidence), free, and owned — the
"we own the risk logic" differentiator (ADR 0005). It plugs into the triage tool exactly
like ``LogFixAdvisor`` does for log findings; the same ``finding_verifier`` /
``RubricMiddleware`` loop grades it against the path evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory


@dataclass(frozen=True)
class RemediationSuggestion:
    """Mirrors the triage pipeline's suggestion shape (likely_cause/suggested_fix/confidence)."""

    likely_cause: str
    suggested_fix: str
    confidence: str  # high | medium | low

    def to_dict(self) -> dict:
        return {
            "likely_cause": self.likely_cause,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
        }


class AttackPathRemediationAdvisor:
    def suggest(
        self,
        *,
        category: str,
        entry_label: str,
        target_label: str,
        feedback: str = "",
    ) -> RemediationSuggestion:
        entry = entry_label or "the public entry"
        target = target_label or "the reachable asset"

        if category == AttackPathCategory.PUBLIC_COMPUTE_ADMIN.value:
            suggestion = RemediationSuggestion(
                likely_cause=(
                    f"{entry} is publicly exposed and can assume a role that grants administrative "
                    f"privileges ({target}) — a public foothold with a direct path to full control."
                ),
                suggested_fix=(
                    f"Break the chain at either end: remove {entry}'s public exposure (tighten its "
                    f"security group / drop the public IP), or detach the over-privileged policy "
                    f"{target} from the role and re-grant least privilege. Prefer scoping the role — "
                    f"it removes the escalation even if the host stays reachable."
                ),
                confidence="high",
            )
        elif category == AttackPathCategory.PUBLIC_DATA_EXPOSURE.value:
            suggestion = RemediationSuggestion(
                likely_cause=(
                    f"{entry} is publicly exposed and can reach the sensitive data store {target} — "
                    f"a public foothold with a path to the crown-jewel data."
                ),
                suggested_fix=(
                    f"Scope the role's access to {target} to least privilege (or remove it), confirm "
                    f"{target} is not itself publicly readable, and remove {entry}'s public exposure "
                    f"if it is not required to be internet-facing."
                ),
                confidence="high",
            )
        else:
            suggestion = RemediationSuggestion(
                likely_cause=(
                    f"{entry} (public) has a toxic path to {target}. The specific escalation depends "
                    f"on the edges in the chain."
                ),
                suggested_fix=(
                    f"Sever the shortest link between {entry} and {target}: remove the public exposure, "
                    f"or strip the privilege/route that makes {target} reachable."
                ),
                confidence="medium",
            )

        if feedback.strip():
            # The rubric/verifier asked for a more grounded answer; name the chain explicitly.
            suggestion = RemediationSuggestion(
                likely_cause=suggestion.likely_cause,
                suggested_fix=f"{suggestion.suggested_fix} (Addressing the review: the path runs {entry} → {target}.)",
                confidence=suggestion.confidence,
            )
        return suggestion
