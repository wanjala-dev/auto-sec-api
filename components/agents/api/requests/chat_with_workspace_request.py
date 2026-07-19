"""Request DTO for POST /ai/chat/workspaces/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatWithWorkspaceRequest:
    """Input DTO for POST /ai/chat/workspaces/ endpoint.

    Chat with workspace data and documents.
    """
    query: str
    workspace_id: str
    conversation_id: str | None = None
    k: int = 5
    stream: bool = False
    context: dict[str, Any] = field(default_factory=dict)
