"""Port for IP → geolocation lookup used by session enrichment.

Framework-free. The concrete adapter (MaxMind GeoLite2) lives in
infrastructure; the application layer only sees this interface and the
``GeoLocation`` value carrier.

Lookups are best-effort observability: an adapter MUST return ``None``
(never raise) when the database is absent, the IP is private/invalid, or
the address is simply not in the database. Dev/test/CI run without a
GeoLite2 mmdb on disk and enrichment must still succeed with blank geo
fields.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GeoLocation:
    """Resolved geolocation for a client IP."""

    city: str
    country: str
    country_code: str


class GeoIPPort(ABC):
    """Secondary/driven port for geo-locating a client IP address."""

    @abstractmethod
    def lookup(self, ip: str) -> GeoLocation | None:
        """Resolve ``ip`` to a :class:`GeoLocation`.

        Returns ``None`` (never raises) for missing databases, private or
        invalid addresses, and addresses not present in the database.
        """
