"""ContextualRiskScorer — the explainable 4-signal blend that ranks findings (ADR 0013 D1).

Pure, deterministic, no LLM, no I/O. Blends **CVSS/severity (impact) × EPSS (likelihood,
gating) × CISA KEV (confirmed-exploited, dominant) × graph-exposure (reachability,
amplifier)** into a 0–100 score, banded by the existing ``RiskBand.from_score`` 34/67
cutoffs, and returns the ``RiskFactor`` breakdown so the HUD shows *why* — never an opaque
number (William: "make the person a fan of what they're risking").

This generalizes ``cloud_graph.RiskScoreCalculator`` (per-workspace) to the per-finding
grain; D5 names the convergence (the workspace score becomes a rollup of these). All
weights live here as module constants (D6) so tuning is a single reviewed edit, mirroring
``RiskBand.from_score``'s "thresholds in one place". Every score stamps ``MODEL_VERSION``
so a blend change is auditable.

Signals map onto CISA BOD 26-04's four questions: impact ("total compromise?"), EPSS
("automatable / likely?"), KEV ("confirmed exploited?"), exposure ("internet-facing?").
"""

from __future__ import annotations

from dataclasses import dataclass

from components.shared_kernel.domain.security import RiskBand, Severity

# ── Tunable model constants (ADR 0013 D6 — one place, one reviewed edit) ───────────────
MODEL_VERSION = "contextual-risk-v1"

# Impact I ∈ [0,1] from severity when no numeric CVSS base is present.
_SEVERITY_IMPACT: dict[Severity, float] = {
    Severity.INFORMATIONAL: 0.1,
    Severity.LOW: 0.3,
    Severity.MEDIUM: 0.5,
    Severity.HIGH: 0.75,
    Severity.CRITICAL: 1.0,
}

# Likelihood prior for a finding with NO CVE (CSPM misconfigs) → severity-derived, so a
# public misconfig still outranks a private one and nothing is left "unscored".
_SEVERITY_LIKELIHOOD_PRIOR: dict[Severity, float] = {
    Severity.INFORMATIONAL: 0.05,
    Severity.LOW: 0.10,
    Severity.MEDIUM: 0.20,
    Severity.HIGH: 0.35,
    Severity.CRITICAL: 0.50,
}

# Exposure amplifier E (reachability). Unknown → private (least urgency from absent signal).
_EXPOSURE_AMPLIFIER: dict[str, float] = {"public": 1.0, "internal": 0.7, "private": 0.4}
_UNKNOWN_EXPOSURE_AMPLIFIER = _EXPOSURE_AMPLIFIER["private"]

# EPSS gate: blend = 100 · I · (EPSS_GATE_SLOPE·L + EPSS_GATE_FLOOR) · E — gates, never zeroes.
_EPSS_GATE_SLOPE = 0.7
_EPSS_GATE_FLOOR = 0.3

# KEV is dominant: a KEV finding is floored into the RED band, unconditionally (D1, decision #1).
_KEV_RED_FLOOR = 67.0  # == RiskBand RED cutoff


@dataclass(frozen=True)
class RiskFactor:
    """One explainable contribution to the score — the shape reused from cloud_graph."""

    key: str
    label: str
    points: int
    detail: str


@dataclass(frozen=True)
class FindingRiskScore:
    """The scored result for one finding — the materialized ``FindingRisk`` row's content."""

    value: float  # 0–100 contextual risk
    band: str  # RiskBand.value (green | amber | red)
    factors: tuple[RiskFactor, ...]
    epss: float | None
    epss_percentile: float | None
    in_kev: bool
    exposure: str  # the amplifier bucket actually applied (public|internal|private)
    exposure_unknown: bool
    model_version: str = MODEL_VERSION


def score_finding(
    *,
    severity: Severity,
    cvss_base: float | None,
    has_cve: bool,
    epss: float | None,
    epss_percentile: float | None,
    in_kev: bool,
    exposure: str | None,
) -> FindingRiskScore:
    """Compute the explainable 0–100 contextual-risk score for one finding (ADR 0013 D1)."""
    # Impact I — real CVSS base when captured, else the severity mapping.
    if cvss_base is not None:
        impact = max(0.0, min(1.0, cvss_base / 10.0))
        impact_detail = f"CVSS {cvss_base:.1f} base"
    else:
        impact = _SEVERITY_IMPACT[severity]
        impact_detail = f"severity {severity.value} (no CVSS base)"

    # Likelihood L — EPSS when the CVE is in the snapshot, else severity-derived prior.
    if epss is not None:
        likelihood = max(0.0, min(1.0, epss))
        pct_txt = f" ({round((epss_percentile or 0.0) * 100)}th pct)" if epss_percentile is not None else ""
        likelihood_detail = f"EPSS {likelihood:.3f}{pct_txt}"
    else:
        likelihood = _SEVERITY_LIKELIHOOD_PRIOR[severity]
        likelihood_detail = (
            f"no EPSS for CVE — severity prior {likelihood:.2f}"
            if has_cve
            else f"no CVE — severity prior {likelihood:.2f}"
        )

    # Exposure amplifier E — unknown damps to private but is flagged, never hidden (decision #3).
    exposure_unknown = exposure not in _EXPOSURE_AMPLIFIER
    if exposure_unknown:
        applied_exposure = "private"
        amplifier = _UNKNOWN_EXPOSURE_AMPLIFIER
        exposure_detail = f"exposure unknown — treated as private (×{amplifier})"
    else:
        applied_exposure = exposure  # type: ignore[assignment]
        amplifier = _EXPOSURE_AMPLIFIER[applied_exposure]
        exposure_detail = f"{applied_exposure} (×{amplifier})"

    blend = 100.0 * impact * (_EPSS_GATE_SLOPE * likelihood + _EPSS_GATE_FLOOR) * amplifier

    # KEV dominates: floor into RED (confirmed exploited outranks predicted), full stop.
    value = max(blend, _KEV_RED_FLOOR) if in_kev else blend
    value = max(0.0, min(100.0, value))
    band = RiskBand.from_score(value)

    factors: list[RiskFactor] = []
    if in_kev:
        factors.append(
            RiskFactor(
                key="kev",
                label="CISA KEV",
                points=int(round(_KEV_RED_FLOOR)),
                detail="actively exploited (floored to RED)",
            )
        )
    factors.append(RiskFactor(key="impact", label="Impact", points=int(round(impact * 100)), detail=impact_detail))
    factors.append(
        RiskFactor(key="likelihood", label="Likelihood", points=int(round(likelihood * 100)), detail=likelihood_detail)
    )
    factors.append(
        RiskFactor(key="exposure", label="Exposure", points=int(round(amplifier * 100)), detail=exposure_detail)
    )

    return FindingRiskScore(
        value=round(value, 2),
        band=band.value,
        factors=tuple(factors),
        epss=epss,
        epss_percentile=epss_percentile,
        in_kev=in_kev,
        exposure=applied_exposure,
        exposure_unknown=exposure_unknown,
    )


def extract_cve(attributes: dict) -> str | None:
    """The CVE id a finding carries in its OCSF ``attributes`` bag, if any.

    Trivy writes ``vulnerability_id`` (CVE-…/GHSA-…); other normalizers may use ``cve``.
    Only ``CVE-`` ids map to EPSS/KEV — a GHSA-only advisory has no CVE and degrades to the
    severity prior (ADR 0013 D1 graceful degradation)."""
    for key in ("vulnerability_id", "cve", "cve_id"):
        value = str((attributes or {}).get(key) or "").strip()
        if value.upper().startswith("CVE-"):
            return value
    return None
