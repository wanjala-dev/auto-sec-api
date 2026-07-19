from __future__ import annotations

import pytest

from components.sign_off.application.providers.sign_off_registry_provider import SignOffRegistry
from components.sign_off.application.services.sign_off_service import SignOffService
from components.sign_off.domain.errors import IllegalTransitionError, SignOffError
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import FigureCheck, ReviewerReceipts
from components.sign_off.domain.value_objects.risk_band import RiskBand
from components.sign_off.domain.value_objects.sign_off_target import Audience, SignOffTarget
from components.sign_off.tests.unit.fakes import FakeAudit, FakeSignOffAdapter

pytestmark = pytest.mark.unit

CLEAN = ReviewerReceipts(
    figure_checks=(FigureCheck("$32k", "32000", "32000", verified=True),),
)
CONTRADICTED = ReviewerReceipts(
    figure_checks=(FigureCheck("$40k", "40000", "32000", verified=False),),
)


def _service(adapter):
    registry = SignOffRegistry()
    registry.register(adapter)
    audit = FakeAudit()
    return SignOffService(registry=registry, audit=audit), audit


def test_green_artifact_one_click_approves_and_audits():
    adapter = FakeSignOffAdapter("newsletter", state=ReviewState.PENDING, receipts=CLEAN)
    service, audit = _service(adapter)

    assert service.assess("newsletter", "n1") == RiskBand.GREEN
    result = service.approve("newsletter", "n1", actor_id="u1")

    assert result == ReviewState.APPROVED
    assert adapter.get_state("n1") == ReviewState.APPROVED
    assert audit.entries[-1]["event"] == "approved"
    assert audit.entries[-1]["detail"]["band"] == "green"


def test_red_artifact_blocks_one_click_approve():
    adapter = FakeSignOffAdapter("report", state=ReviewState.PENDING, receipts=CONTRADICTED)
    service, _ = _service(adapter)

    assert service.assess("report", "r1") == RiskBand.RED
    with pytest.raises(SignOffError):
        service.approve("report", "r1", actor_id="u1")  # no override reason
    # state unchanged — the gate held
    assert adapter.get_state("r1") == ReviewState.PENDING


def test_red_artifact_approves_with_override_reason():
    adapter = FakeSignOffAdapter("report", state=ReviewState.PENDING, receipts=CONTRADICTED)
    service, audit = _service(adapter)

    result = service.approve("report", "r1", actor_id="u1", override_reason="figure is a rounding label, confirmed")
    assert result == ReviewState.APPROVED
    assert audit.entries[-1]["detail"]["override_reason"]


def test_high_stakes_clean_is_amber_and_still_one_click():
    adapter = FakeSignOffAdapter(
        "grant_draft",
        state=ReviewState.PENDING,
        receipts=CLEAN,
        target=SignOffTarget(Audience.EXTERNAL, high_stakes=True),
    )
    service, _ = _service(adapter)
    # external + high-stakes escalates green -> amber, but amber is still one-click
    assert service.assess("grant_draft", "g1") == RiskBand.AMBER
    assert service.approve("grant_draft", "g1", actor_id="u1") == ReviewState.APPROVED


def test_reject_is_terminal():
    adapter = FakeSignOffAdapter("blog", state=ReviewState.PENDING, receipts=CLEAN)
    service, _ = _service(adapter)
    service.reject("blog", "b1", actor_id="u1", codes=("unsafe",), note="off-brand")
    assert adapter.get_state("b1") == ReviewState.REJECTED
    with pytest.raises(IllegalTransitionError):
        service.approve("blog", "b1", actor_id="u1")


def test_request_changes_then_resubmit_then_approve():
    adapter = FakeSignOffAdapter("newsletter", state=ReviewState.PENDING, receipts=CLEAN)
    service, _ = _service(adapter)
    service.request_changes("newsletter", "n1", actor_id="u1", codes=("incomplete",), note="add impact")
    assert adapter.get_state("n1") == ReviewState.CHANGES_REQUESTED
    service.submit_for_review("newsletter", "n1", actor_id="author")
    assert adapter.get_state("n1") == ReviewState.PENDING
    assert service.approve("newsletter", "n1", actor_id="u1") == ReviewState.APPROVED
