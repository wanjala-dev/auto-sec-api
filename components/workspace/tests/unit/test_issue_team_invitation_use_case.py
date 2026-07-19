from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.membership.application.use_cases.issue_invitation_use_case import (
    IssueInvitationUseCase,
)
from components.membership.domain.errors import InvitationValidationError


def test_issue_team_invitation_requires_email():
    use_case = IssueInvitationUseCase(invitation_store=Mock())

    try:
        use_case.execute(
            workspace="workspace",
            team="team",
            invitee="invitee",
            email="",
            actor_id="actor-1",
        )
    except InvitationValidationError as exc:
        assert str(exc) == "Invitee email is required."
    else:
        raise AssertionError("Expected InvitationValidationError when invitee email is missing.")


def test_issue_team_invitation_normalizes_email_and_delegates():
    store = SimpleNamespace(
        issue_invitation=Mock(
            return_value={
                "status": "added",
                "email": "invitee@example.com",
                "invitee": "invitee",
                "invitation": "invitation",
            }
        )
    )
    use_case = IssueInvitationUseCase(invitation_store=store)

    result = use_case.execute(
        workspace="workspace",
        team="team",
        invitee="invitee",
        email=" Invitee@example.com ",
        actor_id="actor-1",
    )

    assert result.status == "added"
    assert result.email == "invitee@example.com"
    store.issue_invitation.assert_called_once_with(
        workspace="workspace",
        team="team",
        invitee="invitee",
        email="invitee@example.com",
        actor_id="actor-1",
    )
