"""Pure alert-delivery policy — the severity gate. No framework, no IO."""

from __future__ import annotations

# Worst-first severity ranking (matches shared_kernel Severity.value —
# "informational", not "info"). A sink's ``min_severity`` is the operator's noise
# dial: only findings at or above it are delivered. ``info`` is accepted as an alias.
_SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "informational": 1, "info": 1}

DEFAULT_MIN_SEVERITY = "high"


def severity_meets_threshold(severity: str, min_severity: str) -> bool:
    """True when ``severity`` is at least as severe as ``min_severity``.

    Unknown severities rank 0 (never delivered on their own); an unknown/blank
    threshold falls back to the default so a mis-set sink stays conservative.
    """
    threshold = _SEVERITY_RANK.get((min_severity or "").lower()) or _SEVERITY_RANK[DEFAULT_MIN_SEVERITY]
    return _SEVERITY_RANK.get((severity or "").lower(), 0) >= threshold
