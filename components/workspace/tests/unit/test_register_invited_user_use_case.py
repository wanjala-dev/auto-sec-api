from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.workspace.application.use_cases.register_invited_user_use_case import (
    RegisterInvitedUserUseCase,
)


def test_register_invited_user_use_case_delegates_to_port():
    port = SimpleNamespace(register_or_get_invited_user=Mock(return_value="user"))
    use_case = RegisterInvitedUserUseCase(
        invited_user_registration_port=port,
    )

    result = use_case.execute(
        email="invitee@example.com",
        name="invitee",
        workspace_id="workspace-1",
        team_name="Alpha",
        request="request",
    )

    assert result == "user"
    port.register_or_get_invited_user.assert_called_once_with(
        email="invitee@example.com",
        name="invitee",
        workspace_id="workspace-1",
        team_name="Alpha",
        request="request",
        site_domain=None,
    )
