"""ContainerVulnRemediationAdvisor — how to fix a container-image CVE (owned risk logic).

The consumer half of the Trivy pipeline: given a normalised vulnerability finding (its CVE
id + package + installed/fixed version), produce a GROUNDED remediation that names the
actual package and the exact version to move to. Deterministic (no LLM) — Trivy already
told us the fixed version, so the fix is a function of the finding: inherently grounded,
free, owned. Plugs into the triage tool exactly like the log/cloud advisors; the same
``finding_verifier`` / RubricMiddleware loop grades it against the CVE evidence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VulnRemediationSuggestion:
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


class ContainerVulnRemediationAdvisor:
    def suggest(
        self,
        *,
        vulnerability_id: str,
        pkg_name: str,
        installed_version: str,
        fixed_version: str,
        feedback: str = "",
    ) -> VulnRemediationSuggestion:
        cve = vulnerability_id or "the vulnerability"
        pkg = pkg_name or "the affected package"
        installed = installed_version or "the installed version"

        if fixed_version.strip():
            suggestion = VulnRemediationSuggestion(
                likely_cause=(
                    f"The image ships {pkg} {installed}, which is affected by {cve}. A fixed "
                    f"version ({fixed_version}) is available."
                ),
                suggested_fix=(
                    f"Upgrade {pkg} from {installed} to {fixed_version} (or later) — bump the base "
                    f"image or the package pin, then rebuild and re-scan to confirm {cve} clears."
                ),
                confidence="high",
            )
        else:
            suggestion = VulnRemediationSuggestion(
                likely_cause=(
                    f"The image ships {pkg} {installed}, affected by {cve}. No upstream fix is published yet."
                ),
                suggested_fix=(
                    f"No fixed version for {cve} yet: mitigate by removing or replacing {pkg} if it "
                    f"is not required, applying the advisory's workaround, or restricting exposure of "
                    f"the affected path; track the advisory and upgrade when a fix lands."
                ),
                confidence="medium",
            )

        if feedback.strip():
            suggestion = VulnRemediationSuggestion(
                likely_cause=suggestion.likely_cause,
                suggested_fix=f"{suggestion.suggested_fix} (Addressing the review: the CVE is {cve} in {pkg}.)",
                confidence=suggestion.confidence,
            )
        return suggestion
