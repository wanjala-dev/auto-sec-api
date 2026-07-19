from __future__ import annotations

from typing import Any, Protocol


class WorkspaceStaffAccountPort(Protocol):
    def ensure_staff_member(
        self,
        *,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        is_active: bool,
        photo_url: str | None,
        staff_team: Any,
        contributors_team: Any,
    ) -> None: ...
