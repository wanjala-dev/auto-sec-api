"""ORM adapter for teammate profile read/write operations.

Extracted from agents_controller.py update_teammate_profile.
"""
from __future__ import annotations

import logging

from components.agents.domain.errors import (
    AgentNotFoundError,
    AgentPermissionError,
)
from components.agents.application.ports.teammate_profile_port import (
    GetTeammateProfileRequest,
    TeammateProfileData,
    TeammateProfilePort,
    UpdateTeammateProfileCommand,
    UpdateTeammateProfileResult,
)

logger = logging.getLogger(__name__)


class OrmTeammateProfileRepository(TeammateProfilePort):

    @staticmethod
    def _get_workspace(workspace_id: str):
        from infrastructure.persistence.workspaces.models import Workspace
        try:
            return Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            raise AgentNotFoundError("Workspace not found")

    @staticmethod
    def _check_permissions(user, workspace, *, include_followers: bool = False) -> None:
        if not user or not workspace:
            raise AgentPermissionError("Permission denied")
        if getattr(user, "is_staff", False):
            return
        if str(workspace.workspace_owner_id) == str(getattr(user, "id", None)):
            return
        if workspace.workspace_teams.filter(members=user, status="active").exists():
            return
        if include_followers and workspace.followers.filter(id=getattr(user, "id", None)).exists():
            return
        raise AgentPermissionError("Permission denied")

    @staticmethod
    def _resolve_alias(profile):
        """Return the most appropriate alias stored on the teammate profile."""
        if not profile:
            return None
        alias = profile.display_name
        if alias:
            return alias
        config = profile.config or {}
        alias = config.get("display_name")
        if alias:
            return alias
        profile_section = config.get("profile")
        if isinstance(profile_section, dict):
            return profile_section.get("name")
        return None

    @staticmethod
    def _ensure_profile(workspace):
        from components.agents.infrastructure.services.actions_service import get_ai_action_service
        profile = getattr(workspace, "ai_teammate_profile", None)
        if not profile:
            action_service = get_ai_action_service()
            profile = action_service.ensure_teammate(workspace)
        return profile

    def get_teammate_profile(self, *, request: GetTeammateProfileRequest) -> TeammateProfileData:
        workspace = self._get_workspace(request.workspace_id)
        self._check_permissions(request.user, workspace, include_followers=True)
        profile = self._ensure_profile(workspace)
        alias = self._resolve_alias(profile)
        return TeammateProfileData(
            workspace_id=str(workspace.id),
            display_name=alias,
            avatar_url=getattr(profile, "avatar_url", "") or "",
        )

    def update_teammate_profile(self, *, command: UpdateTeammateProfileCommand) -> UpdateTeammateProfileResult:
        from components.agents.infrastructure.services.agents_service import get_agent_service

        workspace = self._get_workspace(command.workspace_id)
        self._check_permissions(command.user, workspace, include_followers=False)
        profile = self._ensure_profile(workspace)

        # PATCH semantics: an absent field (None) is left untouched, so an
        # avatar-only update can't wipe the name and vice versa. For the
        # name, an empty/whitespace value still clears back to the default
        # (the pre-avatar contract — the FE sends "" to reset).
        alias_provided = command.display_name is not None
        alias = None
        update_fields = ["updated_at"]

        if alias_provided:
            alias = command.display_name.strip() or None

            config = dict(profile.config or {})
            if alias:
                config["display_name"] = alias
                profile_section = config.setdefault("profile", {})
                profile_section["name"] = alias
            else:
                config.pop("display_name", None)
                profile_section = config.get("profile")
                if isinstance(profile_section, dict) and "name" in profile_section:
                    profile_section.pop("name")

            profile.display_name = alias
            profile.config = config
            update_fields += ["display_name", "config"]

        # Avatar: "" = reset to the platform default, anything else = the
        # new avatar. Bounded to the column width so an oversized URL can't
        # fail the save after the name half already mutated in memory.
        if command.avatar_url is not None:
            profile.avatar_url = command.avatar_url.strip()[:1000]
            update_fields.append("avatar_url")

        profile.save(update_fields=update_fields)

        if alias_provided:
            # Sync the AI user's auth ``first_name`` so anywhere a user row is
            # rendered by name (task assignee lists, audit authors, mentions)
            # the assistant identifies by the alias the workspace chose.
            try:
                ai_user = profile.user
                desired_first_name = (alias or "AI")[:30]
                if ai_user and ai_user.first_name != desired_first_name:
                    ai_user.first_name = desired_first_name
                    ai_user.save(update_fields=["first_name"])
            except Exception:
                logger.exception(
                    "failed_to_sync_ai_user_first_name workspace_id=%s alias=%s",
                    workspace.id, alias,
                )

            # Ensure the teammate agent picks up the new alias
            service = get_agent_service()
            try:
                service.ensure_teammate_agent(str(workspace.id))
            except Exception:
                pass

            # Sync the AI-agents team title with the new alias so the Kanban
            # board's team name mirrors the assistant's name.
            try:
                from components.agents.infrastructure.services.agent_permissions_service import (
                    ensure_agents_team,
                )
                ensure_agents_team(workspace, profile.user)
            except Exception:
                logger.exception(
                    "failed_to_sync_agents_team_title workspace_id=%s alias=%s",
                    workspace.id, alias,
                )

        return UpdateTeammateProfileResult(
            workspace_id=str(workspace.id),
            display_name=alias if alias_provided else self._resolve_alias(profile),
            avatar_url=getattr(profile, "avatar_url", "") or "",
        )
