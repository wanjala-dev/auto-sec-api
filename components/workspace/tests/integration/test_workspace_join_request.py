"""Integration tests for the workspace join request flow."""

from __future__ import annotations

import pytest

from components.workspace.application.ports.workspace_join_request_port import (
    CreateJoinRequestCommand,
    ReviewJoinRequestCommand,
    WithdrawJoinRequestCommand,
)
from components.workspace.domain.errors import (
    JoinRequestAlreadyExistsError,
    JoinRequestPermissionError,
    JoinRequestValidationError,
)
from components.workspace.infrastructure.repositories.workspace_join_request_repository import (
    OrmWorkspaceJoinRequestRepository,
)


@pytest.fixture
def private_workspace(workspace_factory):
    return workspace_factory(privacy="private")


@pytest.fixture
def public_workspace(workspace_factory):
    return workspace_factory(privacy="public")


@pytest.fixture
def join_request_store():
    return OrmWorkspaceJoinRequestRepository()


@pytest.mark.django_db
class TestCreateJoinRequest:
    def test_requester_gets_pending_request(
        self, private_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        result = join_request_store.create_request(
            command=CreateJoinRequestCommand(
                workspace_id=str(private_workspace.id),
                requester_id=str(requester.id),
                message="I'd love to help.",
            )
        )
        assert result.status == "pending"
        assert result.workspace_id == str(private_workspace.id)
        assert result.requester_id == str(requester.id)
        assert result.message == "I'd love to help."

    def test_owner_cannot_request_own_workspace(
        self, private_workspace, join_request_store
    ):
        with pytest.raises(JoinRequestValidationError):
            join_request_store.create_request(
                command=CreateJoinRequestCommand(
                    workspace_id=str(private_workspace.id),
                    requester_id=str(private_workspace.workspace_owner_id),
                )
            )

    def test_public_workspace_rejects_join_request(
        self, public_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        with pytest.raises(JoinRequestValidationError):
            join_request_store.create_request(
                command=CreateJoinRequestCommand(
                    workspace_id=str(public_workspace.id),
                    requester_id=str(requester.id),
                )
            )

    def test_duplicate_pending_request_is_rejected(
        self, private_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        join_request_store.create_request(
            command=CreateJoinRequestCommand(
                workspace_id=str(private_workspace.id),
                requester_id=str(requester.id),
            )
        )
        with pytest.raises(
            (JoinRequestValidationError, JoinRequestAlreadyExistsError)
        ):
            join_request_store.create_request(
                command=CreateJoinRequestCommand(
                    workspace_id=str(private_workspace.id),
                    requester_id=str(requester.id),
                )
            )


@pytest.mark.django_db
class TestApproveDenyWithdraw:
    def test_owner_approves_and_creates_membership(
        self, private_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        created = join_request_store.create_request(
            command=CreateJoinRequestCommand(
                workspace_id=str(private_workspace.id),
                requester_id=str(requester.id),
            )
        )
        approved = join_request_store.approve_request(
            command=ReviewJoinRequestCommand(
                request_id=created.request_id,
                reviewer_id=str(private_workspace.workspace_owner_id),
                note="welcome",
            )
        )
        assert approved.status == "approved"
        assert approved.review_note == "welcome"
        assert approved.membership_id is not None

        from django.apps import apps

        WorkspaceMembership = apps.get_model("workspaces", "WorkspaceMembership")
        assert WorkspaceMembership.objects.filter(
            workspace_id=private_workspace.id,
            user_id=requester.id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists()

    def test_owner_can_deny_with_note(
        self, private_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        created = join_request_store.create_request(
            command=CreateJoinRequestCommand(
                workspace_id=str(private_workspace.id),
                requester_id=str(requester.id),
            )
        )
        denied = join_request_store.deny_request(
            command=ReviewJoinRequestCommand(
                request_id=created.request_id,
                reviewer_id=str(private_workspace.workspace_owner_id),
                note="not a fit right now",
            )
        )
        assert denied.status == "denied"
        assert denied.review_note == "not a fit right now"

    def test_non_admin_cannot_approve(
        self, private_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        random_user = user_factory()
        created = join_request_store.create_request(
            command=CreateJoinRequestCommand(
                workspace_id=str(private_workspace.id),
                requester_id=str(requester.id),
            )
        )
        with pytest.raises(JoinRequestPermissionError):
            join_request_store.approve_request(
                command=ReviewJoinRequestCommand(
                    request_id=created.request_id,
                    reviewer_id=str(random_user.id),
                )
            )

    def test_requester_can_withdraw_while_pending(
        self, private_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        created = join_request_store.create_request(
            command=CreateJoinRequestCommand(
                workspace_id=str(private_workspace.id),
                requester_id=str(requester.id),
            )
        )
        withdrawn = join_request_store.withdraw_request(
            command=WithdrawJoinRequestCommand(
                request_id=created.request_id,
                actor_id=str(requester.id),
            )
        )
        assert withdrawn.status == "withdrawn"

    def test_other_user_cannot_withdraw(
        self, private_workspace, user_factory, join_request_store
    ):
        requester = user_factory()
        other = user_factory()
        created = join_request_store.create_request(
            command=CreateJoinRequestCommand(
                workspace_id=str(private_workspace.id),
                requester_id=str(requester.id),
            )
        )
        with pytest.raises(JoinRequestPermissionError):
            join_request_store.withdraw_request(
                command=WithdrawJoinRequestCommand(
                    request_id=created.request_id,
                    actor_id=str(other.id),
                )
            )
