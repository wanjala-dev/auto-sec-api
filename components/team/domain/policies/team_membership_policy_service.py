from __future__ import annotations


# "General" for teamspaces ("Contributors" collided with the Contributor
# persona/role — nav rework); "Family" stays for personal workspaces.
DEFAULT_ORG_TEAM_TITLE = "General"
DEFAULT_PERSONAL_TEAM_TITLE = "Family"


class TeamMembershipPolicyService:
    def default_team_title(self, *, is_personal_workspace: bool) -> str:
        if is_personal_workspace:
            return DEFAULT_PERSONAL_TEAM_TITLE
        return DEFAULT_ORG_TEAM_TITLE

    def should_activate_team(self, *, current_status: str, active_status: str) -> bool:
        return current_status != active_status

    def profile_context_updates(
        self,
        *,
        current_active_workspace_id,
        current_active_team_id,
        workspace_id,
        team_id,
        update_active_context: bool,
    ) -> dict[str, object]:
        updates: dict[str, object] = {}

        # Workspace pointer: None is the only "absent" marker. active_workspace_id
        # is a nullable UUID, so 0 / False never occur in production — but treat
        # them as present (not absent) so the method is correct for any caller and
        # never overwrites an existing value or drops a legitimate 0.
        if workspace_id is not None:
            if update_active_context:
                if current_active_workspace_id != workspace_id:
                    updates["active_workspace_id"] = workspace_id
            elif current_active_workspace_id is None:
                updates["active_workspace_id"] = workspace_id

        # Team pointer: active_team_id is a non-null IntegerField whose 0 is the
        # "no team" sentinel, so a current value of 0 means "no active team yet"
        # and MUST be fillable — hence the truthiness check (`not current...`),
        # not `is None`. The outer `team_id is not None` guard prevents writing
        # active_team_id=None (which would violate the NOT NULL constraint) when
        # no team was provided.
        if team_id is not None:
            if update_active_context:
                if current_active_team_id != team_id:
                    updates["active_team_id"] = team_id
            elif not current_active_team_id:
                updates["active_team_id"] = team_id

        return updates
