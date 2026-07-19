from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.membership.application.use_cases.accept_invitation_use_case import (
    AcceptInvitationUseCase,
)
from components.membership.domain.errors import (
    InvitationValidationError,
    MembershipAuthorizationError,
)


def test_accept_team_invitation_requires_code():
    use_case = AcceptInvitationUseCase(invitation_store=Mock())

    try:
        use_case.execute(code="", actor=SimpleNamespace(is_authenticated=True))
    except InvitationValidationError as exc:
        assert str(exc) == "Invite code is required."
    else:
        raise AssertionError("Expected InvitationValidationError when invite code is missing.")


def test_accept_team_invitation_requires_authenticated_actor():
    use_case = AcceptInvitationUseCase(invitation_store=Mock())

    try:
        use_case.execute(code="CODE", actor=SimpleNamespace(is_authenticated=False))
    except MembershipAuthorizationError as exc:
        assert str(exc) == "Authentication required."
    else:
        raise AssertionError("Expected MembershipAuthorizationError for anonymous actor.")


def test_accept_team_invitation_delegates_to_store():
    store = SimpleNamespace(
        accept_invitation=Mock(return_value="invitation"),
    )
    use_case = AcceptInvitationUseCase(invitation_store=store)
    actor = SimpleNamespace(is_authenticated=True)

    invitation = use_case.execute(code=" CODE ", actor=actor)

    assert invitation == "invitation"
    store.accept_invitation.assert_called_once_with(code="CODE", actor=actor)
