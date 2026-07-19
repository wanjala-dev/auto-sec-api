from __future__ import annotations

from dataclasses import dataclass
import re

from components.workspace.application.ports.workspace_staff_account_port import (
    WorkspaceStaffAccountPort,
)


@dataclass
class SeedStaffAccountsUseCase:
    staff_account_store: WorkspaceStaffAccountPort

    def execute(self, staff_members, *, staff_team, contributors_team) -> None:
        for member in staff_members:
            email = member["email"]
            username = _normalize_username(
                f"{member.get('first_name', '')}.{member.get('last_name', '')}"
            ) or email
            photo_choice = member.get("photo_source_url") or member.get("photo_url")
            if not photo_choice:
                avatar_seed = member.get("first_name") or member.get("last_name") or email.split("@")[0]
                photo_choice = (
                    f"https://api.dicebear.com/6.x/initials/svg?workspace="
                    f"{_normalize_username(avatar_seed or 'team-member') or 'team-member'}"
                )
            self.staff_account_store.ensure_staff_member(
                email=email,
                username=username,
                first_name=member.get("first_name", ""),
                last_name=member.get("last_name", ""),
                is_active=member.get("is_active", True),
                photo_url=photo_choice,
                staff_team=staff_team,
                contributors_team=contributors_team,
            )


def _normalize_username(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return normalized.strip("-")
