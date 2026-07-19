from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from components.sign_off.application.providers.sign_off_registry_provider import SignOffRegistry
from components.sign_off.application.services.sign_off_queue_query import list_pending_sign_offs
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.risk_band import RiskBand
from components.sign_off.domain.value_objects.sign_off_item import ReceiptsSummary, SignOffItem
from components.sign_off.tests.unit.fakes import FakeSignOffAdapter

pytestmark = pytest.mark.unit


def _item(artifact_type, artifact_id, band, created_at):
    return SignOffItem(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        title=f"{artifact_type} {artifact_id}",
        review_state=ReviewState.PENDING,
        risk_band=band,
        audience="external",
        receipts_summary=ReceiptsSummary(),
        workspace_id="ws-1",
        created_at=created_at,
    )


def _dt(day):
    return datetime(2026, 6, day, tzinfo=timezone.utc)


def test_merges_and_sorts_red_amber_green_then_oldest_first():
    # newsletter emits a green (day 1) + a red (day 5); reports emits an amber
    # (day 2) + an older red (day 3).
    newsletter = FakeSignOffAdapter(
        "newsletter",
        pending=[
            _item("newsletter", "n-green", RiskBand.GREEN, _dt(1)),
            _item("newsletter", "n-red-new", RiskBand.RED, _dt(5)),
        ],
    )
    reports = FakeSignOffAdapter(
        "financial_report",
        pending=[
            _item("financial_report", "r-amber", RiskBand.AMBER, _dt(2)),
            _item("financial_report", "r-red-old", RiskBand.RED, _dt(3)),
        ],
    )
    registry = SignOffRegistry()
    registry.register(newsletter)
    registry.register(reports)

    items = list_pending_sign_offs("ws-1", registry=registry)

    # red (oldest first) -> amber -> green
    assert [it.artifact_id for it in items] == [
        "r-red-old",
        "n-red-new",
        "r-amber",
        "n-green",
    ]


def test_one_failing_adapter_is_skipped_not_fatal(caplog):
    good = FakeSignOffAdapter(
        "newsletter",
        pending=[_item("newsletter", "n1", RiskBand.AMBER, _dt(1))],
    )
    broken = FakeSignOffAdapter(
        "financial_report",
        list_pending_error=RuntimeError("adapter blew up"),
    )
    registry = SignOffRegistry()
    registry.register(good)
    registry.register(broken)

    with caplog.at_level(logging.ERROR, logger="components.sign_off"):
        items = list_pending_sign_offs("ws-1", registry=registry)

    assert [it.artifact_id for it in items] == ["n1"]
    assert any("list_pending_failed" in r.message for r in caplog.records)


def test_undated_items_sort_after_dated_within_band():
    adapter = FakeSignOffAdapter(
        "newsletter",
        pending=[
            _item("newsletter", "undated", RiskBand.AMBER, None),
            _item("newsletter", "dated", RiskBand.AMBER, _dt(1)),
        ],
    )
    registry = SignOffRegistry()
    registry.register(adapter)

    items = list_pending_sign_offs("ws-1", registry=registry)
    assert [it.artifact_id for it in items] == ["dated", "undated"]
