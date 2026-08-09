"""VercelApiPort — the driven-side contract for probing a Vercel connection (ADR 0021 D2).

Deliberately tiny: P0 needs only the verify() surface — token validity, team
resolution, and (best-effort) the token's own expiry so the panel can nag before it
lapses. Posture scanning does NOT go through this port: the scan is the Prowler
engine in its ephemeral Job (ADR 0021 D3); this port exists so the connection
lifecycle service stays SDK/HTTP-free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class VercelHealth:
    """Outcome of a probe. ``detail`` is operator-safe (scrubbed, never the token)."""

    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class VercelTeam:
    """The resolved team trio — recorded on the connection by verify()."""

    id: str
    slug: str = ""
    name: str = ""


class VercelApiPort(ABC):
    """Probe a Vercel API token + its team access. Adapters never raise for an
    expected auth/access failure — they return a ``VercelHealth`` with the reason."""

    @abstractmethod
    def verify_token(self) -> VercelHealth:
        """``GET /v2/user`` — the exact call Prowler validates credentials with:
        401 → invalid/revoked token; 403 → insufficient/disabled; 429 → rate-limited."""

    @abstractmethod
    def get_team(self, team: str) -> tuple[VercelHealth, VercelTeam | None]:
        """Resolve *team* (id or slug) and confirm the token can read it."""

    @abstractmethod
    def get_token_expiry(self) -> datetime | None:
        """The current token's expiry, when the API exposes it. Best-effort —
        returns ``None`` on any failure (expiry display is a nicety, never a gate)."""
