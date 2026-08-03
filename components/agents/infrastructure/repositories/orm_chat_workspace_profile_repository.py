"""ORM adapter implementing :class:`ChatWorkspaceProfilePort`.

Reads the workspace mission/vision/story (``workspaces.Workspace``) and the
assistant display name (``ai.AITeammateProfile``) — the exact ORM reads
``agent_chat_use_case._build_workspace_profile_context`` did inline, moved behind
the port so the use case no longer imports persistence. Both reads are
failure-safe: a broken lookup returns ``None`` / ``""`` so profile assembly (and
the chat) never breaks.
"""

from __future__ import annotations

import logging

from components.agents.application.ports.chat_workspace_profile_port import (
    ChatWorkspaceProfilePort,
    WorkspaceMissionFields,
)

logger = logging.getLogger(__name__)


class OrmChatWorkspaceProfileRepository(ChatWorkspaceProfilePort):
    def get_mission_fields(self, workspace_id: str) -> WorkspaceMissionFields | None:
        if not workspace_id:
            return None
        try:
            from infrastructure.persistence.workspaces.models import Workspace
        except Exception:
            return None
        try:
            workspace = Workspace.objects.filter(id=workspace_id).only("mission", "vision", "workspace_story").first()
        except Exception:
            logger.debug("Could not load Workspace for profile context", exc_info=True)
            return None
        if workspace is None:
            return None
        return WorkspaceMissionFields(
            mission=getattr(workspace, "mission", "") or "",
            vision=getattr(workspace, "vision", "") or "",
            workspace_story=getattr(workspace, "workspace_story", "") or "",
        )

    def get_assistant_name(self, workspace_id: str) -> str:
        if not workspace_id:
            return ""
        try:
            from infrastructure.persistence.ai.models import AITeammateProfile

            row = AITeammateProfile.objects.filter(workspace_id=workspace_id).only("display_name", "config").first()
        except Exception:
            logger.debug("Could not load teammate profile for context", exc_info=True)
            return ""
        if row is None:
            return ""
        config = row.config if isinstance(row.config, dict) else {}
        profile_section = config.get("profile")
        # The config-JSON fallbacks mirror OrmTeammateProfileRepository's alias
        # resolution for legacy rows renamed before display_name was a column.
        name = (
            row.display_name
            or config.get("display_name")
            or (profile_section.get("name") if isinstance(profile_section, dict) else None)
            or ""
        )
        return str(name).strip()
