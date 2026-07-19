"""Command and result value objects for workspace AI teammate synchronization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SyncWorkspaceAiTeammateCommand:
    """Command to synchronize AI teammate settings for a workspace.

    Attributes:
        workspace: The workspace object to sync AI teammate settings for.
    """

    workspace: object
