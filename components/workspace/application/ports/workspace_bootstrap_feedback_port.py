from __future__ import annotations

from typing import Protocol


class WorkspaceBootstrapFeedbackPort(Protocol):
    def success(self, message: str) -> None: ...

    def notice(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...
