"""Severity + indicative-CVSS value objects.

The SOC board stores a coarse severity band (``critical`` / ``high`` /
``medium`` / ``low``) on ``Task.metadata["severity"]``, derived from a 0-100
impact score (``_derive_severity``: >=70 high, >=40 medium, else low; a
``critical`` band exists in the wire contract for future high-impact detectors).

A pentest report is expected to carry a CVSS 3.1 score per finding. We DO NOT
run scanners that emit CVSS vectors, so a real base score cannot be computed.
Rather than fabricate one, we map each band to an **indicative** midpoint of its
CVSS severity range and flag it as indicative everywhere it appears. This is the
honest position: the number communicates the band on the standard 0-10 scale
without claiming a vector-derived precision we do not have.

Pure domain: no Django, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical band order, highest first — drives the histogram + matrix sort.
SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low")

# Bands we recognise; anything else normalises to "low" (never dropped).
_KNOWN_BANDS = frozenset(SEVERITY_ORDER)

# Indicative CVSS 3.1 base score per band — the midpoint of the CVSS severity
# range for that band (Critical 9.0-10.0 → 9.5; High 7.0-8.9 → 8.0; Medium
# 4.0-6.9 → 5.5; Low 0.1-3.9 → 2.5). Flagged indicative wherever rendered.
_INDICATIVE_CVSS: dict[str, float] = {
    "critical": 9.5,
    "high": 8.0,
    "medium": 5.5,
    "low": 2.5,
}

# Print colours per band (used by the severity banner + matrix + histogram).
_BAND_COLOR: dict[str, str] = {
    "critical": "#b00020",
    "high": "#c2410c",
    "medium": "#b7791f",
    "low": "#2f7d32",
}

# One-line meaning per band for Appendix B.
_BAND_MEANING: dict[str, str] = {
    "critical": "Direct compromise of the application, its data, or its users with little effort. Fix immediately.",
    "high": "Exposure of credentials or sensitive data, or an action that crosses a privilege boundary. Fix in the current cycle.",
    "medium": "A weakness that needs a further condition or some user interaction to cause harm. Plan a fix soon.",
    "low": "Limited impact on its own, or useful mainly in combination with another issue. Fix as routine maintenance.",
}


def normalize_band(raw: str | None) -> str:
    """Normalise an arbitrary severity string to a known band (default low)."""
    band = (raw or "").strip().lower()
    return band if band in _KNOWN_BANDS else "low"


@dataclass(frozen=True)
class Severity:
    """A finding's severity band with its indicative CVSS score."""

    band: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "band", normalize_band(self.band))

    @property
    def label(self) -> str:
        return self.band.capitalize()

    @property
    def cvss(self) -> float:
        """Indicative CVSS 3.1 base score — NOT vector-derived."""
        return _INDICATIVE_CVSS[self.band]

    @property
    def color(self) -> str:
        return _BAND_COLOR[self.band]

    @property
    def rank(self) -> int:
        """Sort key — 0 is most severe (critical), 3 least (low)."""
        return SEVERITY_ORDER.index(self.band)


def band_meaning(band: str) -> str:
    return _BAND_MEANING[normalize_band(band)]


def band_color(band: str) -> str:
    return _BAND_COLOR[normalize_band(band)]
