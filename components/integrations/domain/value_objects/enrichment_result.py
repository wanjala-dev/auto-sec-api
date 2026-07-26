"""Normalized threat-intel enrichment result — provider-agnostic by design."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from components.integrations.domain.value_objects.indicator import Indicator


class EnrichmentVerdict(str, Enum):
    MALICIOUS = "malicious"
    SUSPICIOUS = "suspicious"
    BENIGN = "benign"
    UNKNOWN = "unknown"  # not found, unsupported, or provider unavailable


@dataclass(frozen=True)
class EnrichmentResult:
    """One provider's normalized read on an indicator.

    ``score`` is a normalized 0–100 threat score so results are comparable across
    providers (VirusTotal engine counts, AbuseIPDB confidence, GreyNoise class, …).
    ``error`` is set (and verdict UNKNOWN) when the lookup couldn't be performed —
    the caller must treat that as "no signal", never as "benign".
    """

    provider: str
    indicator: Indicator
    verdict: EnrichmentVerdict
    score: int = 0
    positives: int | None = None
    detail: str = ""
    error: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.error is None and self.verdict in (
            EnrichmentVerdict.MALICIOUS,
            EnrichmentVerdict.SUSPICIOUS,
        )

    @classmethod
    def unavailable(cls, provider: str, indicator: Indicator, error: str) -> EnrichmentResult:
        return cls(provider=provider, indicator=indicator, verdict=EnrichmentVerdict.UNKNOWN, error=error)

    # Shared cache codec — every adapter caches the same JSON-safe shape (one place so
    # the codec never drifts across providers).
    def to_cache_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "score": self.score,
            "positives": self.positives,
            "detail": self.detail,
            "error": self.error,
        }

    @classmethod
    def from_cache_dict(cls, data: dict, *, provider: str, indicator: Indicator) -> EnrichmentResult:
        return cls(
            provider=provider,
            indicator=indicator,
            verdict=EnrichmentVerdict(data.get("verdict", "unknown")),
            score=int(data.get("score", 0) or 0),
            positives=data.get("positives"),
            detail=data.get("detail", ""),
            error=data.get("error"),
        )


# Severity ordering for corroborating multiple providers — worst real signal wins, so a
# GreyNoise "benign scanner" never downgrades a VirusTotal "malicious".
_SEVERITY_RANK = {
    EnrichmentVerdict.UNKNOWN: 0,
    EnrichmentVerdict.BENIGN: 1,
    EnrichmentVerdict.SUSPICIOUS: 2,
    EnrichmentVerdict.MALICIOUS: 3,
}


@dataclass(frozen=True)
class CorroboratedEnrichment:
    """Aggregate read across providers: the most-severe real verdict + each source."""

    indicator: Indicator
    verdict: EnrichmentVerdict
    score: int
    results: list[EnrichmentResult] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return [r.provider for r in self.results if r.error is None]


def corroborate(indicator: Indicator, results: list[EnrichmentResult]) -> CorroboratedEnrichment:
    """Fold per-provider results into one corroborated verdict (worst real signal, max score)."""
    real = [r for r in results if r.error is None]
    if not real:
        return CorroboratedEnrichment(indicator, EnrichmentVerdict.UNKNOWN, 0, list(results))
    verdict = max(real, key=lambda r: _SEVERITY_RANK[r.verdict]).verdict
    score = max(r.score for r in real)
    return CorroboratedEnrichment(indicator, verdict, score, list(results))
