"""Port: the external-delivery ledger (ADR 0016 D7).

Shaped to what the sender task needs — *let me claim this event for this connection,
and tell me the truth about what happened* — not to the ORM.

Two steps on purpose, mirroring the email channel's record-then-claim:

* ``record`` reserves the (connection, event) pair behind a DB unique constraint.
* ``claim`` is an ATOMIC conditional transition that exactly one caller can win.

Splitting them is what makes a Celery retry safe in both directions. Reserving alone
would let a retry see "row exists" and silently drop a live alert; claiming alone
would let two workers racing the same event both post to a customer's channel. The
claim only succeeds from ``pending``/``failed``, so a ``sent`` row is never redelivered
and a failed one always can be.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class LedgerRecord:
    id: int
    created: bool
    status: str


class ExternalDeliveryLedgerPort(ABC):
    @abstractmethod
    def record(self, *, connection_id: UUID, dedup_key: str, event_key: str) -> LedgerRecord:
        """Reserve this (connection, event) pair, creating the row if absent."""

    @abstractmethod
    def claim(self, record_id: int) -> bool:
        """Atomically take ownership of a deliverable row.

        True exactly once per deliverable state. False when another worker already
        holds it, or when it is terminal (``sent``/``skipped``) — the caller must
        then deliver nothing.
        """

    @abstractmethod
    def mark_sent(self, record_id: int) -> None: ...

    @abstractmethod
    def mark_failed(self, record_id: int, error: str) -> None:
        """Terminal-for-now failure. Stays re-claimable so a Celery retry can pick
        it up; ``attempts`` carries the history."""

    @abstractmethod
    def mark_skipped(self, record_id: int, reason: str) -> None:
        """Recorded, not sent — a flag off, an unsubscribed event, a severity floor.
        The ledger never claims a send that didn't happen."""
