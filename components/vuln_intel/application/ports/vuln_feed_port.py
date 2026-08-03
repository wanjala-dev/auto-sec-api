"""VulnFeedPort — the pinned external threat-intel feed seam (ADR 0013 D2).

The same multi-provider, pinned-external-source shape as ``ScannerPort`` (ADR 0006) and
``LogSourcePort`` (ADR 0008), pointed at threat intelligence. A feed adapter pulls its
source once (over HTTPS, from the authoritative host) and returns a domain snapshot; the
ingest use case persists it. Shaped to the core's need ("give me a dated, versioned pull
of records"), NOT to any one feed's wire format — the EPSS CSV vs the KEV JSON differ, so
each concrete feed has its own typed ``fetch_*`` returning its snapshot type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.vuln_intel.domain.value_objects.feed_snapshot import EpssFeedSnapshot, KevFeedSnapshot


class EpssFeedPort(ABC):
    @abstractmethod
    def fetch(self) -> EpssFeedSnapshot:
        """Pull the current EPSS scores (daily CSV) into a dated, version-stamped snapshot."""


class KevFeedPort(ABC):
    @abstractmethod
    def fetch(self) -> KevFeedSnapshot:
        """Pull the current CISA KEV catalog (JSON) into a versioned snapshot."""
