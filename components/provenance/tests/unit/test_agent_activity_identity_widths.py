"""The identity-width invariant on :class:`AgentActivityRecord` (no DB, no framework).

``origin_id`` is the provenance ledger's idempotency key. Truncating it does not
produce a shorter key — it produces a **wrong** one, and two genuinely distinct
agent actions collide into a single ``ProvenanceEvent``. That is a silent wrong
answer in exactly the surface whose job is to be trustworthy about who did what.

These tests pin both halves of the fix:

* the realistic keys fit, whole and unmodified;
* an over-long key raises here, in the domain, rather than being trimmed to fit.

The guard deliberately lives above the database because the two backends disagree:
PostgreSQL rejects an over-length insert (``value too long for type character
varying(128)``) while SQLite — what ``api.settings.test`` runs — enforces no
VARCHAR length at all and stores the oversized value happily. A guard that relied
on the column would pass in tests and behave differently in production.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.provenance.domain.entities.agent_activity_entity import (
    MAX_ACTION_LENGTH,
    MAX_AGENT_URN_LENGTH,
    MAX_ORIGIN_ID_LENGTH,
    MAX_RESOURCE_REF_LENGTH,
    AgentActivityRecord,
)

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _record(**overrides) -> AgentActivityRecord:
    kwargs = {
        "agent_urn": "urn:agent:vercel:invoice-bot",
        "resource_ref": "api.stripe.com",
        "resource_type": "network_endpoint",
        "action": "execute_tool",
        "occurred_at": _WHEN,
        "trace_id": "5b8aa5a2d2c872e8321cf37308d69df2",
        "span_id": "051581bf3cb55c13",
    }
    kwargs.update(overrides)
    return AgentActivityRecord(**kwargs)


# ── the realistic keys fit ────────────────────────────────────────────────────


def test_w3c_trace_context_key_fits_with_headroom():
    """32-hex trace + 16-hex span = 49 chars — the OTLP case, comfortably inside."""
    record = _record()

    assert record.origin_id == "5b8aa5a2d2c872e8321cf37308d69df2:051581bf3cb55c13"
    assert len(record.origin_id) == 49
    assert len(record.origin_id) < MAX_ORIGIN_ID_LENGTH


def test_uuid_keyed_runtime_survives_whole():
    """``<uuid>:<uuid>`` is 73 chars — over the ORIGINAL 64-char column.

    This is the producer that made the old width a live bug rather than a
    theoretical one: it needed no exotic vendor, just a runtime that keys its
    spans with UUIDs.
    """
    trace, span = str(uuid4()), str(uuid4())

    record = _record(trace_id=trace, span_id=span)

    assert record.origin_id == f"{trace}:{span}"
    assert len(record.origin_id) == 73


def test_two_spans_of_one_long_trace_keep_distinct_keys():
    """The collision the old ``[:64]`` slice caused, pinned shut.

    With a trace id of 64+ chars, truncation discarded the span id entirely, so
    EVERY span in that trace produced the same ``origin_id`` — the first was
    stored and the rest were counted as duplicates and dropped.
    """
    trace = "t" * 90

    first = _record(trace_id=trace, span_id="051581bf3cb55c13")
    second = _record(trace_id=trace, span_id="99e0f1a2b3c4d5e6")

    assert first.origin_id != second.origin_id
    assert first.origin_id.endswith("051581bf3cb55c13")
    assert second.origin_id.endswith("99e0f1a2b3c4d5e6")


# ── over-long identities fail loudly ──────────────────────────────────────────


def test_oversized_origin_id_raises_rather_than_truncating():
    with pytest.raises(ValueError) as excinfo:
        _record(trace_id="t" * 200)

    message = str(excinfo.value)
    assert "origin_id" in message
    assert str(MAX_ORIGIN_ID_LENGTH) in message
    # The full customer-controlled value must not be echoed into an exception
    # that ends up in logs / error tracking.
    assert "t" * 200 not in message


def test_oversized_resource_ref_raises():
    """``resource_ref`` backs ``ProvenanceResource``'s uniqueness — truncating it
    would merge two distinct resources into one node."""
    with pytest.raises(ValueError, match="resource_ref"):
        _record(resource_ref="r" * (MAX_RESOURCE_REF_LENGTH + 1))


def test_oversized_agent_urn_raises():
    """``agent_urn`` backs ``ProvenanceActor``'s uniqueness — truncating it would
    attribute one agent's actions to another."""
    with pytest.raises(ValueError, match="agent_urn"):
        _record(agent_urn="urn:agent:vercel:" + "a" * MAX_AGENT_URN_LENGTH)


@pytest.mark.parametrize("length", [MAX_ORIGIN_ID_LENGTH, MAX_ORIGIN_ID_LENGTH + 1])
def test_the_limit_is_inclusive(length):
    """A key of exactly the column width is valid; one char more is not."""
    trace = "t" * (length - len("051581bf3cb55c13") - 1)

    if length <= MAX_ORIGIN_ID_LENGTH:
        assert len(_record(trace_id=trace).origin_id) == length
    else:
        with pytest.raises(ValueError):
            _record(trace_id=trace)


# ── descriptive fields still truncate, deliberately ───────────────────────────


def test_long_action_truncates_because_it_identifies_nothing():
    """``action`` labels the event; it is not part of any unique key. Losing a
    suffix degrades the label — it cannot merge two events — so dropping the
    whole span over it would be the worse trade."""
    record = _record(action="a" * (MAX_ACTION_LENGTH + 50))

    assert len(record.action) == MAX_ACTION_LENGTH
