"""Port: the workspace's canonical brand voice (tone + guidelines).

The brand kit (workspace context's ``WorkspaceTheme``) is the single home for
voice — this port is how the agents context reads it without importing the
workspace context. Voice is STYLE steering only, never grounding.
"""

from __future__ import annotations

from typing import Protocol


class BrandVoicePort(Protocol):
    def get(self, workspace_id: str) -> dict:
        """Return ``{"tone": str, "guidelines": str}`` for the workspace.

        Implementations must be failure-safe — voice is decoration, so any
        miss/error yields blank fields, never an exception.
        """
        ...
