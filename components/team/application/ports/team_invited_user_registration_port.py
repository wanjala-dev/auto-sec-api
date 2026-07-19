from __future__ import annotations

from typing import Protocol


class TeamInvitedUserRegistrationPort(Protocol):
    def register_or_get_invited_user(
        self,
        *,
        email: str,
        name: str,
        workspace_id,
        team_name: str,
        request=None,
        site_domain: str | None = None,
    ):
        ...
