from __future__ import annotations

from typing import Protocol


class WorkspaceAiTeammateSyncPort(Protocol):
    def sync(self, *, workspace) -> None:
        ...
