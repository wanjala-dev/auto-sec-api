"""Unit tests for the JSON serialiser/deserialiser used by
``CeleryEventPublisher`` to ferry ``DomainEvent`` instances over the
Celery wire.

Discovered during the 2026-05-07 deploy verification: financial-report
events carrying ``date`` fields (``range_start``, ``range_end``) raised
``TypeError: Object of type date is not JSON serializable`` at publish
time, silently dropping the event. The encoder handled UUID + datetime
but not date, time, or Decimal — three types financial / scheduling
events hit constantly. Covered now.

Tests round-trip every supported type so a future shape regression
surfaces here instead of in a prod traceback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from components.shared_kernel.domain.events import DomainEvent
from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
    _deserialise_event,
    _serialise_event,
)


# ── Fixture event types ──────────────────────────────────────────────
#
# Defined module-level so ``_deserialise_event`` can resolve them by
# fully-qualified name (it imports the module + getattrs the class).


@dataclass(frozen=True, kw_only=True)
class _EventWithDate(DomainEvent):
    range_start: date
    range_end: date


@dataclass(frozen=True, kw_only=True)
class _EventWithDecimal(DomainEvent):
    amount: Decimal


@dataclass(frozen=True, kw_only=True)
class _EventWithTime(DomainEvent):
    cutoff: time


@dataclass(frozen=True, kw_only=True)
class _EventWithUUIDAndDatetime(DomainEvent):
    workspace_id: UUID
    scheduled_for: datetime


@dataclass(frozen=True, kw_only=True)
class _MixedEvent(DomainEvent):
    workspace_id: UUID
    range_start: date
    range_end: date
    cutoff: time
    amount: Decimal
    scheduled_for: datetime


@dataclass(frozen=True, kw_only=True)
class _EventWithOptionalFields(DomainEvent):
    # Mirrors real events like ``TransactionCreated.occurred_on: date | None``.
    occurred_on: date | None
    settled_at: datetime | None
    payer_id: UUID | None
    fee: Decimal | None


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestEventEncoder:
    def test_serialise_event_with_date_no_longer_raises(self):
        # Regression for the prod bug. Pre-fix this raised:
        #   TypeError: Object of type date is not JSON serializable.
        event = _EventWithDate(
            range_start=date(2026, 4, 1),
            range_end=date(2026, 4, 30),
        )
        data = _serialise_event(event)
        assert data["range_start"] == "2026-04-01"
        assert data["range_end"] == "2026-04-30"

    def test_serialise_event_with_decimal_preserves_string_form(self):
        # Decimal must serialise as a string, not a float — float would
        # silently round money / accounting values the money-domain
        # code depends on.
        event = _EventWithDecimal(amount=Decimal("1234.56789"))
        data = _serialise_event(event)
        assert data["amount"] == "1234.56789"
        assert isinstance(data["amount"], str)

    def test_serialise_event_with_time_uses_isoformat(self):
        event = _EventWithTime(cutoff=time(9, 30, 0))
        data = _serialise_event(event)
        assert data["cutoff"] == "09:30:00"

    def test_serialise_event_with_uuid_and_datetime_still_works(self):
        # Pre-existing branches; assert they didn't regress when the
        # new branches were added.
        ws_id = uuid4()
        when = datetime(2026, 5, 7, 12, 30, 0, tzinfo=timezone.utc)
        event = _EventWithUUIDAndDatetime(
            workspace_id=ws_id,
            scheduled_for=when,
        )
        data = _serialise_event(event)
        assert data["workspace_id"] == str(ws_id)
        assert data["scheduled_for"] == when.isoformat()

    def test_datetime_check_orders_before_date_check(self):
        # Subtle correctness check: datetime is a subclass of date, so
        # the encoder's isinstance(datetime) branch must come BEFORE
        # the isinstance(date) branch — otherwise every datetime
        # silently loses its time component.
        when = datetime(2026, 5, 7, 12, 30, 45)
        event = _EventWithUUIDAndDatetime(
            workspace_id=uuid4(),
            scheduled_for=when,
        )
        data = _serialise_event(event)
        # If date branch caught it, we'd see "2026-05-07" only.
        assert data["scheduled_for"] == "2026-05-07T12:30:45"
        assert "T" in data["scheduled_for"]


@pytest.mark.unit
class TestEventDeserialiser:
    def _fqn(self, klass: type) -> str:
        return f"{klass.__module__}.{klass.__name__}"

    def test_round_trips_date_fields(self):
        event = _EventWithDate(
            range_start=date(2026, 4, 1),
            range_end=date(2026, 4, 30),
        )
        data = _serialise_event(event)
        rebuilt = _deserialise_event(self._fqn(_EventWithDate), data)
        assert isinstance(rebuilt, _EventWithDate)
        assert rebuilt.range_start == date(2026, 4, 1)
        assert rebuilt.range_end == date(2026, 4, 30)

    def test_round_trips_decimal_fields_without_precision_loss(self):
        event = _EventWithDecimal(amount=Decimal("1234.56789"))
        data = _serialise_event(event)
        rebuilt = _deserialise_event(self._fqn(_EventWithDecimal), data)
        assert isinstance(rebuilt.amount, Decimal)
        assert rebuilt.amount == Decimal("1234.56789")

    def test_round_trips_time_fields(self):
        event = _EventWithTime(cutoff=time(9, 30, 15))
        data = _serialise_event(event)
        rebuilt = _deserialise_event(self._fqn(_EventWithTime), data)
        assert isinstance(rebuilt.cutoff, time)
        assert rebuilt.cutoff == time(9, 30, 15)

    def test_round_trips_uuid_and_datetime_unchanged(self):
        ws_id = uuid4()
        when = datetime(2026, 5, 7, 12, 30, 0, tzinfo=timezone.utc)
        event = _EventWithUUIDAndDatetime(
            workspace_id=ws_id,
            scheduled_for=when,
        )
        data = _serialise_event(event)
        rebuilt = _deserialise_event(
            self._fqn(_EventWithUUIDAndDatetime), data
        )
        assert rebuilt.workspace_id == ws_id
        assert rebuilt.scheduled_for == when

    def test_round_trips_mixed_event_with_every_supported_type(self):
        # The case the prod bug was actually about: a financial-report
        # event carrying both UUIDs, datetimes, dates, and decimals.
        ws_id = uuid4()
        when = datetime(2026, 5, 7, 12, 30, 0, tzinfo=timezone.utc)
        event = _MixedEvent(
            workspace_id=ws_id,
            range_start=date(2026, 4, 1),
            range_end=date(2026, 4, 30),
            cutoff=time(17, 0, 0),
            amount=Decimal("9876.54321"),
            scheduled_for=when,
        )
        data = _serialise_event(event)
        rebuilt = _deserialise_event(self._fqn(_MixedEvent), data)
        assert rebuilt.workspace_id == ws_id
        assert rebuilt.range_start == date(2026, 4, 1)
        assert rebuilt.range_end == date(2026, 4, 30)
        assert rebuilt.cutoff == time(17, 0, 0)
        assert rebuilt.amount == Decimal("9876.54321")
        assert rebuilt.scheduled_for == when

    def test_round_trips_optional_temporal_fields(self):
        # Regression for the 2026-06-19 bug: an ``X | None`` annotation
        # (e.g. ``TransactionCreated.occurred_on: date | None``) was NOT
        # matched by the type-name check, so the field arrived in the
        # handler as a raw ISO ``str`` and ``.isoformat()`` blew up. With
        # the union-aware annotation parsing it rehydrates to real types.
        ws_id = uuid4()
        when = datetime(2026, 6, 19, 8, 0, 0, tzinfo=timezone.utc)
        event = _EventWithOptionalFields(
            occurred_on=date(2026, 6, 19),
            settled_at=when,
            payer_id=ws_id,
            fee=Decimal("12.50"),
        )
        data = _serialise_event(event)
        rebuilt = _deserialise_event(self._fqn(_EventWithOptionalFields), data)
        assert isinstance(rebuilt.occurred_on, date)
        assert rebuilt.occurred_on == date(2026, 6, 19)
        assert isinstance(rebuilt.settled_at, datetime)
        assert rebuilt.settled_at == when
        assert isinstance(rebuilt.payer_id, UUID)
        assert rebuilt.payer_id == ws_id
        assert isinstance(rebuilt.fee, Decimal)
        assert rebuilt.fee == Decimal("12.50")

    def test_optional_fields_left_none_stay_none(self):
        event = _EventWithOptionalFields(
            occurred_on=None, settled_at=None, payer_id=None, fee=None,
        )
        data = _serialise_event(event)
        rebuilt = _deserialise_event(self._fqn(_EventWithOptionalFields), data)
        assert rebuilt.occurred_on is None
        assert rebuilt.settled_at is None
        assert rebuilt.payer_id is None
        assert rebuilt.fee is None
