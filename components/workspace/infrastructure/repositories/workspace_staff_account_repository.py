from __future__ import annotations

from django.utils.text import slugify

from infrastructure.persistence.users.models import CustomUser, UserProfile
from components.workspace.application.ports.workspace_staff_account_port import WorkspaceStaffAccountPort


class WorkspaceStaffAccountRepository(WorkspaceStaffAccountPort):
    def ensure_staff_member(
        self,
        *,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        is_active: bool,
        photo_url: str | None,
        staff_team,
        contributors_team,
    ) -> None:
        normalized_username = slugify(username)[:150] or email
        user, _ = CustomUser.objects.get_or_create(
            email=email,
            defaults={
                "username": normalized_username,
                "first_name": first_name,
                "last_name": last_name,
                "is_active": is_active,
            },
        )
        profile, _ = UserProfile.objects.get_or_create(user=user)

        if photo_url and (not profile.photo_url or profile.photo_url != photo_url[:120]):
            profile.photo_url = photo_url[:120]
            profile.save(update_fields=["photo_url"])

        staff_team.members.add(user)
        contributors_team.members.add(user)

        updates = []
        if not profile.active_team_id:
            profile.active_team_id = staff_team.id
            updates.append("active_team_id")
        if not profile.active_workspace_id:
            profile.active_workspace_id = staff_team.workspace_id
            updates.append("active_workspace_id")
        if updates:
            profile.save(update_fields=updates)
