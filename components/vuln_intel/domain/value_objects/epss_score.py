"""EpssScore — a CVE's exploitation-probability reading (immutable value object).

Carried by the read-only ``VulnIntelPort`` to the contextual-risk scorer: ``score`` is
the probability [0-1] of exploitation in the next 30 days (the likelihood term ``L``),
``percentile`` its rank [0-1] among all scored CVEs (shown as the "EPSS %" badge).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EpssScore:
    score: float  # probability [0-1]
    percentile: float  # rank [0-1]

    def __post_init__(self) -> None:
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"EPSS score must be in [0,1], got {self.score!r}")
        if not (0.0 <= self.percentile <= 1.0):
            raise ValueError(f"EPSS percentile must be in [0,1], got {self.percentile!r}")
