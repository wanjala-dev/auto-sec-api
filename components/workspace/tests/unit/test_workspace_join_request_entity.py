"""Unit tests for the ``WorkspaceJoinRequestEntity`` domain model."""

from __future__ import annotations

import datetime
from uuid import uuid4

import pytest

from components.workspace.domain.entities.workspace_join_request_entity import (
    JoinRequestStatus,
    WorkspaceJoinRequestEntity,
    MAX_MESSAGE_LENGTH,
)


def _make_pending(**overrides) -> WorkspaceJoinRequestEntity:
    payload = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "requester_id": uuid4(),
        "message": "I'd love to contribute.",
        "status": JoinRequestStatus.PENDING,
        "requested_at": datetime.datetime(2026, 4, 18, tzinfo=datetime.timezone.utc),
    }
    payload.update(overrides)
    return WorkspaceJoinRequestEntity(**payload)


class TestWorkspaceJoinRequestEntityInvariants:
    def test_pending_request_has_no_reviewer_metadata(self):
        request = _make_pending()
        assert request.reviewed_at is None
        assert request.reviewed_by_id is None
        assert request.review_note == ""
        assert request.is_pending
        assert not request.is_terminal

    def test_rejects_invalid_status(self):
        with pytest.raises(ValueError):
            _make_pending(status="processing")

    def test_rejects_oversized_message(self):
        with pytest.raises(ValueError):
            _make_pending(message="x" * (MAX_MESSAGE_LENGTH + 1))

    def test_approved_requires_reviewer_metadata(self):
        with pytest.raises(ValueError):
            WorkspaceJoinRequestEntity(
                id=uuid4(),
                workspace_id=uuid4(),
                requester_id=uuid4(),
                message="",
                status=JoinRequestStatus.APPROVED,
                requested_at=datetime.datetime(2026, 4, 18, tzinfo=datetime.timezone.utc),
                reviewed_at=None,
                reviewed_by_id=None,
            )


class TestWorkspaceJoinRequestEntityTransitions:
    def test_approve_returns_new_instance_with_reviewer(self):
        request = _make_pending()
        reviewer_id = uuid4()
        reviewed_at = datetime.datetime(2026, 4, 19, tzinfo=datetime.timezone.utc)

        approved = request.approve(
            reviewer_id=reviewer_id,
            reviewed_at=reviewed_at,
            note="welcome!",
        )

        assert approved.status == JoinRequestStatus.APPROVED
        assert approved.reviewed_by_id == reviewer_id
        assert approved.reviewed_at == reviewed_at
        assert approved.review_note == "welcome!"
        # original is frozen
        assert request.status == JoinRequestStatus.PENDING

    def test_deny_returns_new_instance_with_reviewer(self):
        request = _make_pending()
        reviewer_id = uuid4()
        reviewed_at = datetime.datetime(2026, 4, 19, tzinfo=datetime.timezone.utc)

        denied = request.deny(
            reviewer_id=reviewer_id,
            reviewed_at=reviewed_at,
            note="not a fit",
        )

        assert denied.status == JoinRequestStatus.DENIED
        assert denied.review_note == "not a fit"

    def test_cannot_approve_terminal_request(self):
        request = _make_pending().approve(
            reviewer_id=uuid4(),
            reviewed_at=datetime.datetime.now(datetime.timezone.utc),
        )
        with pytest.raises(ValueError):
            request.approve(
                reviewer_id=uuid4(),
                reviewed_at=datetime.datetime.now(datetime.timezone.utc),
            )

    def test_cannot_deny_terminal_request(self):
        request = _make_pending().deny(
            reviewer_id=uuid4(),
            reviewed_at=datetime.datetime.now(datetime.timezone.utc),
        )
        with pytest.raises(ValueError):
            request.deny(
                reviewer_id=uuid4(),
                reviewed_at=datetime.datetime.now(datetime.timezone.utc),
            )

    def test_withdraw_only_from_pending(self):
        pending = _make_pending()
        withdrawn = pending.withdraw(
            at=datetime.datetime(2026, 4, 18, tzinfo=datetime.timezone.utc)
        )
        assert withdrawn.status == JoinRequestStatus.WITHDRAWN

        with pytest.raises(ValueError):
            withdrawn.withdraw(
                at=datetime.datetime.now(datetime.timezone.utc)
            )
