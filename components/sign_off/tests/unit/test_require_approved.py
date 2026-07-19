from __future__ import annotations

import pytest

from components.sign_off.application.providers.sign_off_registry_provider import SignOffRegistry
from components.sign_off.application.services.require_approved import require_approved
from components.sign_off.domain.errors import NotApprovedError, UnregisteredArtifactError
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.tests.unit.fakes import FakeSignOffAdapter

pytestmark = pytest.mark.unit


def _registry(state: ReviewState) -> SignOffRegistry:
    registry = SignOffRegistry()
    registry.register(FakeSignOffAdapter("report", state=state))
    return registry


def test_approved_passes():
    require_approved("report", "r1", registry=_registry(ReviewState.APPROVED))  # no raise


@pytest.mark.parametrize(
    "state",
    [ReviewState.PENDING, ReviewState.CHANGES_REQUESTED, ReviewState.REJECTED],
)
def test_non_approved_blocks_the_send(state):
    with pytest.raises(NotApprovedError) as exc:
        require_approved("report", "r1", registry=_registry(state))
    assert exc.value.state == state
    assert exc.value.artifact_type == "report"


def test_unregistered_artifact_type_raises():
    with pytest.raises(UnregisteredArtifactError):
        require_approved("never_registered", "x", registry=SignOffRegistry())
