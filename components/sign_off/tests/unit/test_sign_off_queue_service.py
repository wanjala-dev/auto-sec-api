from __future__ import annotations

import pytest

from components.sign_off.application.providers.sign_off_registry_provider import SignOffRegistry
from components.sign_off.application.services.sign_off_queue_service import SignOffQueueService
from components.sign_off.domain.errors import SignOffError
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import FigureCheck, ReviewerReceipts
from components.sign_off.domain.value_objects.sign_off_target import Audience, SignOffTarget
from components.sign_off.tests.unit.fakes import FakeAudit, FakeSignOffAdapter

pytestmark = pytest.mark.unit

CLEAN = ReviewerReceipts(figure_checks=(FigureCheck("$32k", "32000", "32000", verified=True),))
CONTRADICTED = ReviewerReceipts(figure_checks=(FigureCheck("$40k", "40000", "32000", verified=False),))


def _service(adapter):
    registry = SignOffRegistry()
    registry.register(adapter)
    audit = FakeAudit()
    return SignOffQueueService(registry=registry, audit=audit), audit, adapter


def test_green_approve_delegates_to_adapter_and_audits():
    adapter = FakeSignOffAdapter("newsletter", receipts=CLEAN)
    service, audit, adapter = _service(adapter)

    service.approve("newsletter", "n1", actor_id="u1")

    assert adapter.approved == [
        {"artifact_id": "n1", "actor_id": "u1", "override_reason": None}
    ]
    assert audit.entries[-1]["event"] == "approved"
    assert audit.entries[-1]["detail"]["band"] == "green"


def test_red_approve_without_reason_raises_and_does_not_delegate():
    adapter = FakeSignOffAdapter("financial_report", receipts=CONTRADICTED)
    service, audit, adapter = _service(adapter)

    with pytest.raises(SignOffError):
        service.approve("financial_report", "r1", actor_id="u1")

    assert adapter.approved == []  # the delegated action never ran
    assert audit.entries == []  # nothing audited — the gate held


def test_red_approve_with_reason_delegates_and_audits_reason():
    adapter = FakeSignOffAdapter("financial_report", receipts=CONTRADICTED)
    service, audit, adapter = _service(adapter)

    service.approve("financial_report", "r1", actor_id="u1", override_reason="confirmed by CFO")

    assert adapter.approved[0]["override_reason"] == "confirmed by CFO"
    assert audit.entries[-1]["detail"]["override_reason"] == "confirmed by CFO"


def test_high_stakes_clean_is_amber_and_still_one_click():
    adapter = FakeSignOffAdapter(
        "grant_draft",
        receipts=CLEAN,
        target=SignOffTarget(Audience.EXTERNAL, high_stakes=True),
    )
    service, audit, adapter = _service(adapter)

    service.approve("grant_draft", "g1", actor_id="u1")  # no reason needed for amber
    assert adapter.approved[0]["artifact_id"] == "g1"
    assert audit.entries[-1]["detail"]["band"] == "amber"


def test_request_changes_delegates_and_audits():
    adapter = FakeSignOffAdapter("newsletter", receipts=CLEAN)
    service, audit, adapter = _service(adapter)

    service.request_changes("newsletter", "n1", actor_id="u1", codes=("incomplete",), note="add impact")

    assert adapter.changes_requested == [
        {"artifact_id": "n1", "actor_id": "u1", "codes": ("incomplete",), "note": "add impact"}
    ]
    assert audit.entries[-1]["event"] == "changes_requested"
    assert audit.entries[-1]["detail"]["note"] == "add impact"


def test_reject_delegates_and_audits():
    adapter = FakeSignOffAdapter("writing_draft", receipts=CLEAN)
    service, audit, adapter = _service(adapter)

    service.reject("writing_draft", "d1", actor_id="u1", codes=("unsafe",), note="off-brand")

    assert adapter.rejected[0]["artifact_id"] == "d1"
    assert adapter.get_state("d1") == ReviewState.REJECTED
    assert audit.entries[-1]["event"] == "rejected"


def test_detail_returns_state_band_and_full_receipts():
    adapter = FakeSignOffAdapter("newsletter", receipts=CONTRADICTED, state=ReviewState.PENDING)
    service, _, _ = _service(adapter)

    detail = service.detail("newsletter", "n1")
    assert detail.review_state == ReviewState.PENDING
    assert detail.risk_band.value == "red"
    assert detail.receipts.has_contradictions is True


def test_workspace_id_delegates_to_adapter():
    adapter = FakeSignOffAdapter("newsletter", workspace_id="ws-42")
    service, _, _ = _service(adapter)
    assert service.workspace_id("newsletter", "n1") == "ws-42"
