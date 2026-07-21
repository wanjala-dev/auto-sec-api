"""Port for the per-channel notification delivery ledger (T1-S5).

One ledger row per (notification, channel, subscription) — that triple is
the idempotency key, so recording the same delivery twice returns the
existing row instead of double-sending. Senders (T1-S6+) claim a row before
transmitting; terminal transitions are ``sent`` / ``failed`` / ``skipped``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryRecord:
    """Framework-free projection of one ledger row."""

    id: str
    notification_id: str
    channel: str
    subscription_id: str | None
    status: str
    attempts: int
    last_error: str


@dataclass(frozen=True)
class RecordOutcome:
    """Result of recording an attempt — the row plus whether it is new
    (False = this delivery was already recorded; do not enqueue again)."""

    record: DeliveryRecord
    created: bool


class DeliveryLedgerPort(ABC):
    """Secondary/driven port for delivery bookkeeping."""

    @abstractmethod
    def record(
        self,
        *,
        notification_id,
        channel: str,
        subscription_id=None,
    ) -> RecordOutcome:
        """Idempotently record a pending delivery for the idempotency key
        (notification, channel, subscription). Returns the existing row with
        ``created=False`` when it was already recorded."""
        ...

    @abstractmethod
    def claim(self, delivery_id) -> DeliveryRecord | None:
        """Atomically claim a pending row for sending: increment ``attempts``
        and return the fresh record. Returns None when the row is missing or
        already terminal (sent/skipped) — the caller MUST NOT send."""
        ...

    @abstractmethod
    def pending_for(self, *, notification_id, channel: str) -> list[DeliveryRecord]:
        """Return pending ledger rows for one notification+channel."""
        ...

    @abstractmethod
    def deliverable_for(self, *, notification_id, channel: str) -> list[DeliveryRecord]:
        """Return rows a sender may (re)claim: ``pending`` AND ``failed``.

        Mirrors :meth:`claim`'s contract — failed rows are retryable, so a
        Celery retry of the delivery task must see them again. Sent and
        skipped rows are terminal and never returned (re-runs are
        idempotent by omission)."""
        ...

    @abstractmethod
    def mark_sent(self, delivery_id) -> None: ...

    @abstractmethod
    def mark_failed(self, delivery_id, *, error: str) -> None: ...

    @abstractmethod
    def mark_skipped(self, delivery_id, *, reason: str) -> None:
        """Terminal no-send outcome (pref flipped off, sender disabled,
        device expired). ``reason`` lands in ``last_error`` so the ledger
        stays truthful about WHY nothing was sent."""
        ...
