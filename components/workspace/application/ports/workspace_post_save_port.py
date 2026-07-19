from __future__ import annotations

from typing import Any, Protocol


class WorkspacePostSavePort(Protocol):
    def enqueue_embeddings(self, *, workspace: Any) -> None: ...

    def bootstrap_defaults(self, *, workspace: Any) -> None: ...
