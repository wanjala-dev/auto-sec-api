"""Unit tests for ``SubscriptionRegistry`` + ``@subscribes_to``.

The registry is a process-level singleton populated at Django app
``ready()`` via auto-discovery. Naively ``clear()``-ing it between
tests breaks because Python's import cache means a later
``discover()`` cannot re-fire ``@subscribes_to`` on already-imported
handler modules — the production entries vanish for the rest of the
session.

So these tests are *additive*: they snapshot-and-restore around each
test, and assertions filter ``entries()`` to the local ``_FakeEventA``
/ ``_FakeEventB`` event classes so production entries sitting
alongside don't matter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from components.agents.application.subscription_registry_service import (
    SubscriptionRegistry,
    subscribes_to,
)
from components.shared_kernel.domain.events import DomainEvent


# ── Test event classes ─────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class _FakeEventA(DomainEvent):
    payload: str = ""


@dataclass(frozen=True, kw_only=True)
class _FakeEventB(DomainEvent):
    other: int = 0


# ── Fake publisher to assert binding ───────────────────────────────────


class _FakePublisher:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[type[DomainEvent], Any]] = []

    def subscribe(self, event_type, handler) -> None:
        self.subscriptions.append((event_type, handler))


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Snapshot → yield → restore the registry around each test.

    No ``clear()`` — that would lose production entries that can't be
    re-discovered from cached imports.
    """
    saved_entries = list(SubscriptionRegistry._entries)
    saved_discovered = SubscriptionRegistry._discovered
    yield
    SubscriptionRegistry._entries.clear()
    SubscriptionRegistry._entries.extend(saved_entries)
    SubscriptionRegistry._discovered = saved_discovered


def _fake_entries() -> list[tuple[type[DomainEvent], Any]]:
    """Filter the registry to the test fakes only."""
    fakes = {_FakeEventA, _FakeEventB}
    return [
        (et, h) for et, h in SubscriptionRegistry.entries() if et in fakes
    ]


class TestSubscribesToDecorator:
    def test_registers_single_subscription(self):
        @subscribes_to(_FakeEventA)
        def handler(event):
            return None

        local = _fake_entries()
        assert len(local) == 1
        assert local[0][0] is _FakeEventA
        assert local[0][1] is handler

    def test_returns_original_function_unchanged(self):
        def raw(event):
            return "raw-return"

        decorated = subscribes_to(_FakeEventA)(raw)

        assert decorated is raw
        assert decorated("anything") == "raw-return"

    def test_stacking_for_multiple_events(self):
        @subscribes_to(_FakeEventA)
        @subscribes_to(_FakeEventB)
        def handler(event):
            return None

        local = _fake_entries()
        events = {e[0] for e in local}
        assert events == {_FakeEventA, _FakeEventB}
        assert all(e[1] is handler for e in local)


class TestRegisterDeduplication:
    def test_same_handler_event_pair_registered_twice_is_one_entry(self):
        def handler(event):
            return None

        SubscriptionRegistry.register(_FakeEventA, handler)
        SubscriptionRegistry.register(_FakeEventA, handler)

        local = _fake_entries()
        assert len(local) == 1

    def test_different_handlers_same_event_both_registered(self):
        def handler_one(event):
            return None

        def handler_two(event):
            return None

        SubscriptionRegistry.register(_FakeEventA, handler_one)
        SubscriptionRegistry.register(_FakeEventA, handler_two)

        local = _fake_entries()
        assert len(local) == 2


class TestBindAll:
    def test_passes_each_subscription_to_publisher(self):
        @subscribes_to(_FakeEventA)
        def handler_a(event):
            return None

        @subscribes_to(_FakeEventB)
        def handler_b(event):
            return None

        publisher = _FakePublisher()
        SubscriptionRegistry.bind_all(publisher)

        recorded = {(et, h) for et, h in publisher.subscriptions}
        assert (_FakeEventA, handler_a) in recorded
        assert (_FakeEventB, handler_b) in recorded


class TestEntriesIsACopy:
    def test_mutating_returned_list_does_not_affect_registry(self):
        @subscribes_to(_FakeEventA)
        def handler(event):
            return None

        before = len(SubscriptionRegistry.entries())
        snapshot = SubscriptionRegistry.entries()
        snapshot.clear()

        assert len(SubscriptionRegistry.entries()) == before


class TestClearForTests:
    def test_clear_removes_subscriptions_added_in_this_test(self):
        @subscribes_to(_FakeEventA)
        def handler(event):
            return None

        # Confirm the test handler was registered before clearing.
        assert any(
            et is _FakeEventA for et, _ in SubscriptionRegistry.entries()
        )

        SubscriptionRegistry.clear()
        assert SubscriptionRegistry.entries() == []
