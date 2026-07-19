from __future__ import annotations

from components.team.application.ports.team_invited_user_registration_port import (
    TeamInvitedUserRegistrationPort,
)


class RegisterInvitedUserUseCase:
    def __init__(
        self,
        *,
        invited_user_registration_port: TeamInvitedUserRegistrationPort,
    ) -> None:
        self.invited_user_registration_port = invited_user_registration_port

    def execute(
        self,
        *,
        email: str,
        name: str,
        workspace_id,
        team_name: str,
        request=None,
        site_domain: str | None = None,
    ):
        return self.invited_user_registration_port.register_or_get_invited_user(
            email=email,
            name=name,
            workspace_id=workspace_id,
            team_name=team_name,
            request=request,
            site_domain=site_domain,
        )
