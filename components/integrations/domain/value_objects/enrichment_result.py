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
