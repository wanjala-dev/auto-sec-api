"""Return value from the dispatch port.

Captures how many recipients were actually delivered vs failed per send.
The use case uses this to populate the ``NewsletterSent`` event's
``subscriber_count`` with the truth, not the input list length.

Failed per-recipient sends do NOT bubble as exceptions from the adapter
— they're logged and counted. A blanket transport failure (SMTP down,
auth error) DOES still bubble. The contract: the adapter only swallows
per-row failures; whole-batch failures must raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DispatchSummary:
    delivered: int = 0
    failed: int = 0
    # Per-recipient outcomes (task #25 — send metrics). Empty tuples for
    # adapters that predate tracking; when populated, the dispatch ledger
    # uses them to finalize each recipient's record.
    delivered_emails: tuple[str, ...] = field(default_factory=tuple)
    failed_emails: tuple[str, ...] = field(default_factory=tuple)

    @property
    def attempted(self) -> int:
        return self.delivered + self.failed
