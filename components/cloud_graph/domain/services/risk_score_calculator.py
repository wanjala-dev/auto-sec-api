"""RiskScoreCalculator — one opinionated workspace risk score (owned risk logic).

Not raw CVSS or a finding count (the vanity the research warns against): the score is
**attack-path-led** — a live, exploitable toxic path (public entry → crown jewel) is the
~1% that actually matters, so it dominates. Critical/high findings add on top but are
capped so a noisy scanner can't drown the signal. Deterministic + explainable (it returns
the factor breakdown), like the rest of our advisor logic — read-only, no LLM.

Convention: ``value`` is the RISK (0–100, higher = worse); ``posture`` is ``100 - value``
(higher = safer) for a health-style gauge. The caller picks which to display.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Component caps — attack paths dominate; findings are capped so raw volume can't drown them.
_ATTACK_CAP = 60.0
_FINDINGS_CAP = 35.0


@dataclass(frozen=True)
class RiskFactor:
    key: str
    label: str
    points: int
    detail: str


@dataclass(frozen=True)
class RiskScore:
    value: int  # 0–100, higher = worse (the risk)
    band: str  # critical | high | medium | low
    posture: int  # 100 - value (higher = safer) — for a health-style gauge
    factors: tuple[RiskFactor, ...]

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "band": self.band,
            "posture": self.posture,
            "factors": [{"key": f.key, "label": f.label, "points": f.points, "detail": f.detail} for f in self.factors],
        }


def _band(value: int) -> str:
    if value >= 75:
        return "critical"
    if value >= 50:
        return "high"
    if value >= 25:
        return "medium"
    return "low"


def calculate(
    *,
    attack_path_scores: Sequence[float],
    critical: int,
    high: int,
    medium: int,
) -> RiskScore:
    """Compose the risk score from live attack paths (dominant) + open finding severity."""
    paths = list(attack_path_scores)
    if paths:
        worst = max(paths)
        # worst single path drives most of it; extra paths add a smaller marginal bump.
        attack_points = min(_ATTACK_CAP, worst * 0.5 + (len(paths) - 1) * 5.0)
    else:
        worst = 0.0
        attack_points = 0.0

    finding_points = min(_FINDINGS_CAP, critical * 6.0 + high * 2.0 + medium * 0.3)

    value = int(round(min(100.0, attack_points + finding_points)))
    factors = (
        RiskFactor(
            key="attack_paths",
            label="Attack paths",
            points=int(round(attack_points)),
            detail=(
                f"{len(paths)} live toxic path(s), worst score {int(round(worst))}" if paths else "no live attack paths"
            ),
        ),
        RiskFactor(
            key="findings",
            label="Open findings",
            points=int(round(finding_points)),
            detail=f"{critical} critical · {high} high · {medium} medium (open)",
        ),
    )
    return RiskScore(value=value, band=_band(value), posture=100 - value, factors=factors)
