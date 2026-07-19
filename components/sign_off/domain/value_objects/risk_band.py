"""Risk band — how much review friction an artifact gets.

The band never changes *whether* a human signs (the gate is universal); it
changes *how much scrutiny* the reviewer is forced into, so green items clear
fast and human attention concentrates on amber/red. This is what lets a
universal hard gate scale instead of collapsing into rubber-stamping.
"""

from __future__ import annotations

from enum import Enum


class RiskBand(str, Enum):
    GREEN = "green"  # verified + sourced + on-voice: one-click approve
    AMBER = "amber"  # flags present: reviewer must acknowledge each before approve
    RED = "red"  # contradicts the ledger / high-stakes: edit or override-with-reason, escalate


# Severity ordering for "worst-of" combination + one-step escalation.
_ORDER: tuple[RiskBand, ...] = (RiskBand.GREEN, RiskBand.AMBER, RiskBand.RED)


def escalate(band: RiskBand, steps: int = 1) -> RiskBand:
    """Raise ``band`` by ``steps`` severity levels, capped at RED."""
    idx = min(_ORDER.index(band) + max(0, steps), len(_ORDER) - 1)
    return _ORDER[idx]


def worst(*bands: RiskBand) -> RiskBand:
    """Return the most severe of the given bands (GREEN if none)."""
    if not bands:
        return RiskBand.GREEN
    return max(bands, key=_ORDER.index)
