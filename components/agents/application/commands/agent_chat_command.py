"""Command + result types for the unified agent chat path.

Every chat message runs through the deep-agent pipeline
(``DeepPlanAndRunUseCase``) with grounding injected at the planner.
There is no fallback path, no keyword routing, and no embedding fallback
shim — the one honest path is: persona/entitlement checks → deep run
with retrieval context → extract answer.

Framework-free; lives in the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.shared_kernel.application.commands import Command


@dataclass(frozen=True, kw_only=True)
class AgentChatCommand(Command):
    """Input command for the unified chat endpoint."""

    query: str
    workspace_id: UUID
    user_id: UUID
    user_email: str = ""
    user_full_name: str = ""
    username: str = ""
    persona_role: str = ""
    conversation_id: UUID | None = None
    agent_type: str = "workspace_agent"
    agent_config_extra: dict = field(default_factory=dict)
    # Optional client-supplied plan_id. The chat UI generates this
    # before issuing the request so it can open a WebSocket
    # subscription to ``resource.agent_run.<plan_id>`` *before* the
    # backend has even started the orchestrator. The user then sees
    # ``ctx.info()`` / ``ctx.report_progress()`` events stream into the
    # tool-call card live, instead of staring at "Thinking..." until
    # the run finishes. If the client doesn't send one, the use case
    # falls back to a server-generated UUID and the experience
    # degrades to the prior "progress card mounts after the answer"
    # behaviour.
    plan_id: UUID | None = None


@dataclass(frozen=True)
class AgentChatSuccess:
    """Successful chat response — the agent produced a grounded answer."""

    response: str
    workspace_id: str
    query: str
    agent_type: str
    plan_id: str = ""
    conversation_id: str | None = None
    source: str = "deep_agent"
    # UUID of the persisted assistant ``ConversationMessage`` — used
    # by the frontend to attach per-message thumbs-up/thumbs-down
    # feedback via POST /ai/conversations/<conv>/messages/<id>/feedback/.
    message_id: str | None = None
    # RAG chunks that informed this answer. Each entry is a
    # ``{section, section_title, content, score}`` dict — same shape
    # ``deep_service._prefetch_retrieved_context`` produces. Surfaced
    # in the HTTP response so the frontend can render the citations
    # panel under the new assistant bubble immediately, without
    # waiting for a conversation reload to pick up
    # ``ConversationMessage.metadata.sources``. Empty list when the
    # planner answered without RAG grounding (degenerate goals,
    # workspaces with no indexed knowledge base, etc.).
    sources: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class AgentChatFailure:
    """Chat failure — persona/entitlement refused, or the deep run errored.

    For workspace quota exceedances (``status_code == 429``),
    ``quota_info`` carries the remaining-budget snapshot so the
    frontend can render an accurate "X messages remaining, resets at Y"
    banner without a follow-up request. None for any other failure.
    """

    error: str
    workspace_id: str
    query: str
    agent_type: str | None = None
    conversation_id: str | None = None
    status_code: int = 422
    quota_info: dict | None = None
