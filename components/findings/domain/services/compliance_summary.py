"""The compliance posture summary — the shape behind the HUD's Compliance card.

Prowler tags each finding against 40+ frameworks (CIS, PCI-DSS, SOC 2, ISO 27001,
HIPAA, NIST, FedRAMP…) with the specific controls it FAILS. We only ever see
failures (there is no pass denominator), so a "94% compliant" number would be
fabricated. The honest metric is **distinct failing controls per framework**,
rolled up across all open findings, for a curated set of recognizable frameworks.
"""

from __future__ import annotations

from dataclasses import dataclass

# (display name, lowercased key prefixes to match). Prowler emits versioned keys
# (CIS-2.0, CIS-1.4, NIST-800-53-Revision-5, …); we bucket by family so the card
# reads "CIS AWS: N failing controls" rather than a dozen near-duplicate rows.
_CURATED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("CIS AWS", ("cis-", "cis_", "cis ")),
    ("PCI-DSS", ("pci",)),
    ("SOC 2", ("soc2", "soc-2", "soc 2")),
    ("ISO 27001", ("iso27001", "iso-27001", "iso 27001")),
    ("HIPAA", ("hipaa",)),
    ("NIST CSF", ("nist-csf", "nist csf")),
    ("NIST 800-53", ("nist-800-53", "nist 800-53")),
    ("GDPR", ("gdpr",)),
    ("FedRAMP", ("fedramp",)),
    ("AWS FSBP", ("aws-foundational-security-best-practices",)),
)


# Cap the sample of control ids carried per framework — the drill-down callout shows
# these; `failing_controls` still reports the true total. Keeps the summary payload bounded
# (a framework like PCI can fail 300+ controls).
_CONTROLS_SAMPLE = 40


@dataclass(frozen=True)
class ComplianceFramework:
    name: str
    failing_controls: int
    controls: tuple[str, ...] = ()  # sorted sample (≤ _CONTROLS_SAMPLE) of failing control ids


@dataclass(frozen=True)
class ComplianceSummary:
    frameworks: tuple[ComplianceFramework, ...]  # only those with failures, most first
    frameworks_with_failures: int
    total_failing_controls: int

    def to_dict(self) -> dict:
        return {
            "frameworks": [
                {
                    "name": f.name,
                    "failing_controls": f.failing_controls,
                    "controls": list(f.controls),
                }
                for f in self.frameworks
            ],
            "frameworks_with_failures": self.frameworks_with_failures,
            "total_failing_controls": self.total_failing_controls,
        }


def build(compliance_bags: list[dict]) -> ComplianceSummary:
    """Roll up open findings' compliance tags into distinct failing controls per
    curated framework. Distinct within a framework family (a control id failing on
    N findings counts once); the card shows the worst-hit frameworks first."""
    controls: dict[str, set[str]] = {name: set() for name, _ in _CURATED}
    for bag in compliance_bags:
        if not bag:
            continue
        for key, ctrls in bag.items():
            key_l = str(key).lower()
            for name, prefixes in _CURATED:
                if any(key_l.startswith(p) for p in prefixes):
                    controls[name].update(ctrls or [])
                    break
    rows = [
        ComplianceFramework(
            name=name,
            failing_controls=len(controls[name]),
            controls=tuple(sorted(controls[name])[:_CONTROLS_SAMPLE]),
        )
        for name, _ in _CURATED
        if controls[name]
    ]
    rows.sort(key=lambda r: r.failing_controls, reverse=True)
    return ComplianceSummary(
        frameworks=tuple(rows),
        frameworks_with_failures=len(rows),
        total_failing_controls=sum(r.failing_controls for r in rows),
    )
