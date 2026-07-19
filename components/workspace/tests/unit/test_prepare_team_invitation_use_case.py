from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.membership.application.use_cases.prepare_invitation_use_case import (
    PrepareInvitationUseCase,
)
from components.membership.domain.errors import MembershipAuthorizationError


def test_prepare_team_invitation_requires_authenticated_actor():
    use_case = PrepareInvitationUseCase(invitation_store=Mock())

    try:
        use_case.execute(
            workspace_id="workspace-1",
            team_id=None,
            actor=SimpleNamespace(is_authenticated=False),
            emails=["invitee@example.com"],
        )
    except MembershipAuthorizationError as exc:
        assert str(exc) == "Authentication required."
    else:
        raise AssertionError("Expected MembershipAuthorizationError for anonymous actor.")


def test_prepare_team_invitation_normalizes_and_deduplicates_emails():
    store = SimpleNamespace(
        prepare_invitation_batch=Mock(
            return_value={
                "workspace": "workspace",
                "team": "team",
                "existing_users": [],
                "new_emails": ["invitee@example.com"],
                "missing_user_ids": [],
            }
        )
    )
    use_case = PrepareInvitationUseCase(invitation_store=store)
    actor = SimpleNamespace(is_authenticated=True)

    batch = use_case.execute(
        workspace_id="workspace-1",
        team_id=None,
        actor=actor,
        emails=[" Invitee@example.com ", "invitee@example.com", ""],
    )

    assert batch.new_emails == ["invitee@example.com"]
    store.prepare_invitation_batch.assert_called_once_with(
        workspace_id="workspace-1",
        team_id=None,
        actor=actor,
        normalized_emails=["invitee@example.com"],
        user_ids=[],
        is_staff=False,
        is_superuser=False,
    )
