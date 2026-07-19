"""Port: the workspace's canonical brand voice (tone + guidelines).

The brand kit (workspace context's ``WorkspaceTheme``) is the single voice
home — this port is how the content context reads it for AI newsletter/draft
generation without importing the workspace context. Voice is STYLE steering
only, never grounding, and must never fail a draft.
"""

from __future__ import annotations

from typing import Protocol


class BrandVoicePort(Protocol):
    def get(self, workspace_id: str) -> dict:
        """Return ``{"tone": str, "guidelines": str}`` for the workspace.

        Implementations must be failure-safe — any miss/error yields blank
        fields, never an exception.
        """
        ...
