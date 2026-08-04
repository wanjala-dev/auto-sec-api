"""Guards on the shared external-event catalog (ADR 0016 D4)."""

from __future__ import annotations

import pytest

from components.shared_kernel.domain.delivery_events import (
    DEFAULT_EXTERNAL_EVENT_KEYS,
    EXTERNAL_EVENT_CATALOG,
    EXTERNAL_EVENT_KEYS,
    is_known_event_key,
)

pytestmark = pytest.mark.unit


def test_model_default_matches_the_catalog_defaults():
    """The persistence default is a literal (so persistence stays free of
    bounded-context imports). This is the guard that keeps the two from drifting —
    without it, a new default-on event would never reach new connections.
    """
    from infrastructure.persistence.integrations.models import default_delivery_events

    assert tuple(default_delivery_events()) == DEFAULT_EXTERNAL_EVENT_KEYS


def test_keys_are_unique():
    keys = [event.key for event in EXTERNAL_EVENT_CATALOG]
    assert len(keys) == len(set(keys))


def test_every_event_carries_a_label_and_description():
    """These render in the Settings panel — a blank one ships an empty checkbox."""
    for event in EXTERNAL_EVENT_CATALOG:
        assert event.label.strip(), f"{event.key} has no label"
        assert event.description.strip(), f"{event.key} has no description"


def test_reserved_events_are_off_by_default():
    """``risk_accept_expiring`` has no emitter yet (ADR 0015 P2) — defaulting it on
    would show operators a subscription that can never fire."""
    reserved = {event.key for event in EXTERNAL_EVENT_CATALOG if not event.default_on}
    assert "risk_accept_expiring" in reserved
    assert "risk_accept_expiring" not in DEFAULT_EXTERNAL_EVENT_KEYS
    assert "risk_accept_expiring" in EXTERNAL_EVENT_KEYS, "reserved is still a valid subscription"


@pytest.mark.parametrize("key", ["draft_pr_opened", "FINDING_CRITICAL", " scan_failed "])
def test_is_known_event_key_normalizes(key):
    assert is_known_event_key(key) is True


@pytest.mark.parametrize("key", ["", "made_up", None])
def test_is_known_event_key_rejects_unknown(key):
    assert is_known_event_key(key) is False
