"""Request DTO for POST /ai/agents/chat/."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentChatRequest:
    """Input DTO for POST /ai/agents/chat/.

    Built from ``request.data`` by the controller; plain dataclass so the
    application layer never sees a DRF-serialised object.
    """

    query: str
    workspace_id: str
    user_id: str
    user_email: str = ""
    username: str = ""
    user_full_name: str = ""
    persona_role: str = ""
    conversation_id: str | None = None
    agent_type: str = "workspace_agent"
