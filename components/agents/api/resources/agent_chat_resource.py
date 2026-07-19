"""Response DTOs for POST /ai/agents/chat/."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from components.agents.application.commands.agent_chat_command import (
    AgentChatFailure,
    AgentChatSuccess,
)


@dataclass(frozen=True)
class AgentChatResource:
    """Success response body for /ai/agents/chat/."""

    response: str
    workspace_id: str
    query: str
    agent_type: str
    plan_id: str
    conversation_id: str | None
    source: str
    message_id: str | None
    # RAG chunks the planner used. Mirrors
    # ``AgentChatSuccess.sources`` — same shape that
    # ``ConversationMessage.metadata.sources`` carries on persisted
    # rows. Present here so the frontend can render the citations
    # panel under the new assistant bubble immediately, without
    # waiting for a conversation reload.
    sources: list[dict] = field(default_factory=list)

    @classmethod
    def from_success(cls, result: AgentChatSuccess) -> "AgentChatResource":
        return cls(
            response=result.response,
            workspace_id=result.workspace_id,
            query=result.query,
            agent_type=result.agent_type,
            plan_id=result.plan_id,
            conversation_id=result.conversation_id,
            source=result.source,
            message_id=result.message_id,
            sources=list(result.sources or []),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentChatErrorResource:
    """Error response body for /ai/agents/chat/.

    For HTTP 429 (workspace quota exceeded), ``quota`` carries the
    remaining-budget snapshot so the chat header can render an
    accurate "X messages remaining, resets at Y" banner without a
    follow-up request. Omitted (None) for any other failure shape.
    """

    error: str
    workspace_id: str
    query: str
    agent_type: str | None
    conversation_id: str | None
    quota: dict | None = None

    @classmethod
    def from_failure(cls, result: AgentChatFailure) -> "AgentChatErrorResource":
        return cls(
            error=result.error,
            workspace_id=result.workspace_id,
            query=result.query,
            agent_type=result.agent_type,
            conversation_id=result.conversation_id,
            quota=result.quota_info,
        )

    def to_dict(self) -> dict:
        return asdict(self)
