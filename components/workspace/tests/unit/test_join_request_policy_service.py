"""Unit tests for ``JoinRequestPolicyService``."""

from __future__ import annotations

import pytest

from components.workspace.domain.errors import (
    JoinRequestPermissionError,
    JoinRequestValidationError,
)
from components.workspace.domain.policies.join_request_policy_service import (
    JoinRequestPolicyService,
)


class TestEnsureWorkspaceIsRequestable:
    def test_public_workspace_is_rejected(self):
        with pytest.raises(JoinRequestValidationError):
            JoinRequestPolicyService.ensure_workspace_is_requestable(
                workspace_privacy="public",
                workspace_is_active=True,
            )

    def test_inactive_workspace_is_rejected(self):
        with pytest.raises(JoinRequestValidationError):
            JoinRequestPolicyService.ensure_workspace_is_requestable(
                workspace_privacy="private",
                workspace_is_active=False,
            )

    def test_private_active_workspace_passes(self):
        JoinRequestPolicyService.ensure_workspace_is_requestable(
            workspace_privacy="private",
            workspace_is_active=True,
        )


class TestEnsureCanRequest:
    def test_owner_cannot_request(self):
        with pytest.raises(JoinRequestValidationError):
            JoinRequestPolicyService.ensure_can_request(
                requester_is_owner=True,
                requester_is_member=False,
                has_pending_request=False,
            )

    def test_existing_member_cannot_request(self):
        with pytest.raises(JoinRequestValidationError):
            JoinRequestPolicyService.ensure_can_request(
                requester_is_owner=False,
                requester_is_member=True,
                has_pending_request=False,
            )

    def test_duplicate_pending_is_rejected(self):
        with pytest.raises(JoinRequestValidationError):
            JoinRequestPolicyService.ensure_can_request(
                requester_is_owner=False,
                requester_is_member=False,
                has_pending_request=True,
            )

    def test_eligible_requester_passes(self):
        JoinRequestPolicyService.ensure_can_request(
            requester_is_owner=False,
            requester_is_member=False,
            has_pending_request=False,
        )


class TestEnsureCanReview:
    def test_unprivileged_user_cannot_review(self):
        with pytest.raises(JoinRequestPermissionError):
            JoinRequestPolicyService.ensure_can_review(
                reviewer_is_owner=False,
                reviewer_is_admin=False,
                reviewer_is_staff=False,
            )

    def test_owner_can_review(self):
        JoinRequestPolicyService.ensure_can_review(
            reviewer_is_owner=True,
            reviewer_is_admin=False,
            reviewer_is_staff=False,
        )

    def test_admin_can_review(self):
        JoinRequestPolicyService.ensure_can_review(
            reviewer_is_owner=False,
            reviewer_is_admin=True,
            reviewer_is_staff=False,
        )

    def test_staff_can_review(self):
        JoinRequestPolicyService.ensure_can_review(
            reviewer_is_owner=False,
            reviewer_is_admin=False,
            reviewer_is_staff=True,
        )


class TestEnsureCanWithdraw:
    def test_non_requester_cannot_withdraw(self):
        with pytest.raises(JoinRequestPermissionError):
            JoinRequestPolicyService.ensure_can_withdraw(
                requester_id="user-a",
                actor_id="user-b",
            )

    def test_requester_can_withdraw(self):
        JoinRequestPolicyService.ensure_can_withdraw(
            requester_id="user-a",
            actor_id="user-a",
        )
