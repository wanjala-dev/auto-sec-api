"""Port: read a workspace's org identity for report branding."""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceIdentity:
    workspace_id: str
    name: str
    logo_url: str


class WorkspaceIdentityPort(abc.ABC):
    @abc.abstractmethod
    def get(self, *, workspace_id: str) -> WorkspaceIdentity:
        """Return the workspace's display name + logo URL for the cover."""
