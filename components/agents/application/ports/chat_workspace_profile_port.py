"""Port: the workspace-authored profile fields the chat planner grounds on.

``AgentChatUseCase._build_workspace_profile_context`` assembles the planner's
``context.workspace_profile`` from three sources: the workspace's mission / vision
/ story (``workspaces.Workspace``), the brand kit's voice (already a port), and
the assistant's name (``ai.AITeammateProfile``). The two ORM reads —
``Workspace`` (cross-context) and ``AITeammateProfile`` (same-context) — used to be
lazy ORM imports inside the application layer (Rule-2 violation). This port is the
sanctioned seam; the ORM lives in the adapter.

Both reads are failure-safe by contract (a broken lookup yields ``None`` so
profile assembly never breaks the chat), matching the prior inline behaviour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceMissionFields:
    """The three owner-authored workspace narrative fields the planner reads."""

    mission: str = ""
    vision: str = ""
    workspace_story: str = ""


class ChatWorkspaceProfilePort(ABC):
    """Read the workspace-authored profile fields for the chat planner."""

    @abstractmethod
    def get_mission_fields(self, workspace_id: str) -> WorkspaceMissionFields | None:
        """Return the workspace's mission/vision/story, or ``None`` when the
        workspace can't be read (failure-safe — never raises)."""

    @abstractmethod
    def get_assistant_name(self, workspace_id: str) -> str:
        """Return the assistant's display name for the workspace, or ``""``.

        Resolves ``AITeammateProfile.display_name`` with the same legacy
        config-JSON fallbacks the teammate-profile repository uses (rows renamed
        before ``display_name`` was a column). Failure-safe — never raises."""
