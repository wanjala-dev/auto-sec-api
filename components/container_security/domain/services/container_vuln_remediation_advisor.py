"""ContainerVulnRemediationAdvisor — how to fix a container-image CVE (owned risk logic).

The consumer half of the Trivy pipeline: given a normalised vulnerability finding (its CVE
id + package + installed/fixed version), produce a GROUNDED remediation that names the
actual package and the exact version to move to. Deterministic (no LLM) — Trivy already
told us the fixed version, so the fix is a function of the finding: inherently grounded,
free, owned. Plugs into the triage tool exactly like the log/cloud advisors; the same
``finding_verifier`` / RubricMiddleware loop grades it against the CVE evidence.

The suggestion also carries a FIX SNIPPET — the artifact for a finding whose remediation
target is the IMAGE, not a repository (public nginx/node images, any image URL a user
points a scan at). There is no repo to open a draft PR against, so the honest artifact is
copy-pasteable Dockerfile / package-manager guidance, rendered by the HUD through the
sanitized code-render primitive. Deterministic, derived only from the finding's own
evidence — inherently grounded.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Distro marker (as it appears in Trivy's target string, e.g. ``nginx:1.16.0
#: (debian 10.3)``) → the package-manager upgrade line for the fix snippet.
_PKG_MANAGER_LINES: tuple[tuple[str, str], ...] = (
    ("alpine", "RUN apk upgrade --no-cache {pkg}"),
    ("debian", "RUN apt-get update && apt-get install -y --only-upgrade {pkg}"),
    ("ubuntu", "RUN apt-get update && apt-get install -y --only-upgrade {pkg}"),
    ("centos", "RUN yum update -y {pkg}"),
    ("redhat", "RUN yum update -y {pkg}"),
    ("rocky", "RUN dnf upgrade -y {pkg}"),
    ("fedora", "RUN dnf upgrade -y {pkg}"),
)


@dataclass(frozen=True)
class VulnRemediationSuggestion:
    """Mirrors the triage pipeline's suggestion shape (likely_cause/suggested_fix/confidence)
    plus the image-target FIX SNIPPET (Dockerfile/package guidance, ``dockerfile`` syntax)."""

    likely_cause: str
    suggested_fix: str
    confidence: str  # high | medium | low
    fix_snippet: str = ""
    fix_snippet_language: str = "dockerfile"

    def to_dict(self) -> dict:
        return {
            "likely_cause": self.likely_cause,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "fix_snippet": self.fix_snippet,
            "fix_snippet_language": self.fix_snippet_language,
        }


def _image_base(target: str) -> str:
    """``nginx:1.16.0 (debian 10.3)`` → ``nginx:1.16.0`` (Trivy's target string)."""
    return (target or "").split(" (")[0].strip()


def _pkg_manager_line(target: str, pkg: str) -> str:
    lowered = (target or "").lower()
    for marker, template in _PKG_MANAGER_LINES:
        if marker in lowered:
            return template.format(pkg=pkg)
    return f"# …or upgrade the package with the image's package manager: {pkg}"


def build_fix_snippet(
    *,
    vulnerability_id: str,
    pkg_name: str,
    installed_version: str,
    fixed_version: str,
    target: str = "",
) -> str:
    """The copy-pasteable image-remediation artifact, from the finding's own facts.

    Two moves, both anchored to the CVE: bump the base image past the fixed
    version (the durable fix), or pin/upgrade the affected package in the
    Dockerfile (the surgical one). When no fixed version exists yet the snippet
    says so honestly instead of inventing a version.
    """
    cve = vulnerability_id or "this vulnerability"
    pkg = pkg_name or "the affected package"
    image = _image_base(target)
    lines: list[str] = []

    if fixed_version.strip():
        lines.append(f"# {cve}: {pkg} {installed_version or '(installed)'} → {fixed_version}")
        if image:
            lines.append(f"# Durable fix — rebuild from a base image that ships {pkg} >= {fixed_version}:")
            lines.append(f"FROM {image}   # ← bump this tag past the fix")
        lines.append("# Surgical fix — upgrade the package in your Dockerfile:")
        lines.append(_pkg_manager_line(target, pkg))
        lines.append(f"# Then rebuild and re-scan to confirm {cve} clears.")
    else:
        lines.append(f"# {cve}: {pkg} {installed_version or '(installed)'} — no fixed version published yet")
        if image:
            lines.append(f"# Current base: FROM {image}")
        lines.append(f"# Mitigate: remove/replace {pkg} if unused, apply the advisory workaround,")
        lines.append("# or restrict exposure of the affected path; upgrade when a fix lands.")
    return "\n".join(lines)


class ContainerVulnRemediationAdvisor:
    def suggest(
        self,
        *,
        vulnerability_id: str,
        pkg_name: str,
        installed_version: str,
        fixed_version: str,
        target: str = "",
        feedback: str = "",
    ) -> VulnRemediationSuggestion:
        cve = vulnerability_id or "the vulnerability"
        pkg = pkg_name or "the affected package"
        installed = installed_version or "the installed version"
        snippet = build_fix_snippet(
            vulnerability_id=vulnerability_id,
            pkg_name=pkg_name,
            installed_version=installed_version,
            fixed_version=fixed_version,
            target=target,
        )

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
                fix_snippet=snippet,
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
                fix_snippet=snippet,
            )

        if feedback.strip():
            suggestion = VulnRemediationSuggestion(
                likely_cause=suggestion.likely_cause,
                suggested_fix=f"{suggestion.suggested_fix} (Addressing the review: the CVE is {cve} in {pkg}.)",
                confidence=suggestion.confidence,
                fix_snippet=suggestion.fix_snippet,
            )
        return suggestion
