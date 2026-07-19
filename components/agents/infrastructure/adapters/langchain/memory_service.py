"""
Agent Memory Service

Bridges AI agents with the existing memory infrastructure for conversation persistence.

All ORM access uses lazy imports to avoid pulling the full model graph at module
level, keeping the adapter loadable even if persistence models change.
"""

import logging
from typing import Any

# LangChain 1.x (2026-07-19): the ConversationBuffer*Memory classes are gone —
# the builders below return the native SQL-window loaders from
# memories/conversation_memory.py, and message construction is ORM-side only.
from .memories.compacting_memory import compacting_memory_builder
from .memories.sql_memory import build_memory
from .memories.window_memory import window_buffer_memory_builder_with_k

logger = logging.getLogger(__name__)


def _get_agent_models():
    """Lazy import Agent and AgentExecution ORM models."""
    from infrastructure.persistence.ai.agents.models import Agent, AgentExecution

    return Agent, AgentExecution


def _get_conversation_models():
    """Lazy import Conversation and ConversationMessage ORM models."""
    from infrastructure.persistence.ai.conversations.models import (
        Conversation,
        ConversationMessage,
    )

    return Conversation, ConversationMessage


class AgentMemoryService:
    """Service for managing agent memory using existing infrastructure"""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        Agent, _ = _get_agent_models()
        self.agent = Agent.objects.get(agent_id=agent_id)

    def get_conversation_id(self) -> str:
        """Get or create conversation ID for this agent (thread-safe)"""
        Conversation, _ = _get_conversation_models()
        from infrastructure.persistence.ai.agents.models import AgentType

        conversation_id = self.agent.config.get("conversation_id") if self.agent.config else None
        agent_type_label = None
        try:
            agent_type_obj = AgentType.objects.filter(slug=self.agent.agent_type).first()
            if agent_type_obj:
                agent_type_label = agent_type_obj.name
        except Exception:
            agent_type_label = None
        agent_display = agent_type_label or self.agent.agent_type

        # Always try to ensure conversation exists before returning ID
        if conversation_id:
            try:
                Conversation.objects.get(id=conversation_id)
                return conversation_id
            except Conversation.DoesNotExist:
                try:
                    Conversation.objects.create(
                        id=conversation_id,
                        user_id=self.agent.user.id,
                        title=f"{agent_display} Conversation",
                        metadata={
                            "agent_id": str(self.agent.agent_id),
                            "agent_type": self.agent.agent_type,
                            "workspace_id": str(self.agent.workspace.id) if self.agent.workspace else None,
                        },
                    )
                    logger.info(
                        "AgentMemoryService.get_conversation_id: Created missing conversation %s", conversation_id
                    )
                    return conversation_id
                except Exception as e:
                    logger.warning(
                        "AgentMemoryService.get_conversation_id: Failed to create conversation with UUID %s: %s. Generating new one.",
                        conversation_id,
                        e,
                    )
                    conversation_id = None

        # Create new conversation if none exists
        if not conversation_id:
            conversation = Conversation.objects.create(
                user_id=self.agent.user.id,
                title=f"{agent_display} Conversation",
                metadata={
                    "agent_id": str(self.agent.agent_id),
                    "agent_type": self.agent.agent_type,
                    "workspace_id": str(self.agent.workspace.id) if self.agent.workspace else None,
                },
            )
            conversation_id = str(conversation.id)

            # Store it in agent config
            self.agent.config = self.agent.config or {}
            self.agent.config["conversation_id"] = conversation_id
            self.agent.save(update_fields=["config"])

            logger.info(
                "AgentMemoryService.get_conversation_id: Updated agent config with conversation_id %s", conversation_id
            )

        return conversation_id

    def get_memory(self, memory_type: str = "buffer", window_size: int = 10) -> Any:
        """
        Get memory instance for this agent

        Args:
            memory_type: 'buffer' or 'window'
            window_size: For window memory, number of exchanges to keep

        Returns:
            LangChain memory instance
        """
        conversation_id = self.get_conversation_id()

        class ChatArgs:
            def __init__(self, conversation_id):
                self.conversation_id = conversation_id

        chat_args = ChatArgs(conversation_id)

        config = self.agent.config or {}
        max_messages = config.get("memory_max_messages")
        max_message_chars = config.get("memory_max_message_chars")
        max_total_chars = config.get("memory_max_total_chars")

        def _coerce_limit(value: Any) -> int | None:
            try:
                limit = int(value)
            except (TypeError, ValueError):
                return None
            return limit if limit > 0 else None

        max_messages = _coerce_limit(max_messages)
        max_message_chars = _coerce_limit(max_message_chars)
        max_total_chars = _coerce_limit(max_total_chars)

        if memory_type == "compacting":
            if max_messages is None:
                max_messages = max(window_size * 2, 1)
            if max_message_chars is None:
                max_message_chars = 2000
            if max_total_chars is None:
                max_total_chars = 12000
            # Try to get a lightweight LLM for compaction
            compaction_llm = None
            try:
                from components.agents.infrastructure.adapters.llm_provider_adapter import LLMFactoryAdapter

                compaction_llm = LLMFactoryAdapter().get_llm(
                    model_name="gpt-4o-mini",
                    temperature=0.0,
                )
            except Exception:
                logger.debug("Could not load compaction LLM — compacting memory will use truncation fallback")
            memory = compacting_memory_builder(
                chat_args,
                k=window_size,
                compaction_llm=compaction_llm,
                max_messages=max_messages,
                max_message_chars=max_message_chars,
                max_total_chars=max_total_chars,
            )
        elif memory_type == "window":
            if max_messages is None:
                max_messages = max(window_size * 2, 1)
            if max_message_chars is None:
                max_message_chars = 2000
            if max_total_chars is None:
                max_total_chars = 12000
            memory = window_buffer_memory_builder_with_k(
                chat_args,
                k=window_size,
                max_messages=max_messages,
                max_message_chars=max_message_chars,
                max_total_chars=max_total_chars,
            )
        else:
            if max_messages is None:
                max_messages = 40
            if max_message_chars is None:
                max_message_chars = 2000
            if max_total_chars is None:
                max_total_chars = 20000
            memory = build_memory(
                chat_args,
                max_messages=max_messages,
                max_message_chars=max_message_chars,
                max_total_chars=max_total_chars,
            )

        return self._ensure_chat_memory_instance(memory, conversation_id)

    def _ensure_chat_memory_instance(self, memory: Any, conversation_id: str) -> Any:
        """Ensure LangChain memory holds a chat history instance, not a class."""
        chat_memory = getattr(memory, "chat_memory", None)

        if isinstance(chat_memory, type):
            try:
                memory.chat_memory = chat_memory(conversation_id=conversation_id)
            except TypeError:
                try:
                    memory.chat_memory = chat_memory()
                except Exception as exc:  # pragma: no cover
                    logger.warning("Unable to coerce chat_memory into an instance: %s", exc)
                    return memory

        if hasattr(memory, "chat_memory") and hasattr(memory.chat_memory, "conversation_id"):
            if memory.chat_memory.conversation_id != conversation_id:
                memory.chat_memory.conversation_id = conversation_id

        return memory

    # ── Message persistence (ORM, no raw SQL) ─────────────────────────

    def _add_message(
        self,
        role: str,
        content: str,
        *,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add a message to the conversation via ORM.

        Also bumps the parent ``Conversation.updated_at`` so the chat
        sidebar's `-updated_at` ordering reflects activity. Without this,
        adding messages doesn't touch the parent row and stale rows
        (e.g. unrelated PDF chats) end up at the top of the list.

        ``artifacts`` is an optional list of dicts the agent layer
        attaches when a tool produced a downloadable result (PDF report,
        generated image, etc.). Stored under ``metadata['artifacts']``
        so the chat history serializer can surface a paperclip icon on
        the bubble. Each entry is a free-form dict, but the frontend
        expects at minimum: ``kind``, ``id``, ``title``,
        ``download_url``, ``mime_type``, ``status``.
        """
        Conversation, ConversationMessage = _get_conversation_models()
        conversation_id = self.get_conversation_id()
        message_metadata: dict[str, Any] = {}
        if artifacts:
            message_metadata["artifacts"] = list(artifacts)
        ConversationMessage.objects.create(
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata=message_metadata,
        )
        try:
            from django.utils import timezone

            Conversation.objects.filter(id=conversation_id).update(
                updated_at=timezone.now(),
            )
        except Exception:  # pragma: no cover - best effort
            logger.debug("Could not bump Conversation.updated_at", exc_info=True)

    def add_user_message(self, content: str) -> None:
        """Add user message to agent memory"""
        self._add_message("human", content)

    def add_agent_message(
        self,
        content: str,
        *,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add agent response to memory.

        ``artifacts`` is forwarded into ``metadata['artifacts']`` so the
        chat bubble can render download affordances (paperclip icon)
        for PDF reports, generated files, etc.
        """
        self._add_message("assistant", content, artifacts=artifacts)

    def add_system_message(self, content: str) -> None:
        """Add system message to memory"""
        self._add_message("system", content)

    def get_conversation_history(
        self,
        limit: int | None = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[dict[str, Any]]:
        """Get conversation history for this agent with pagination support."""
        _, ConversationMessage = _get_conversation_models()
        conversation_id = self.get_conversation_id()

        order_field = "created_at" if str(order).lower() != "desc" else "-created_at"
        qs = (
            ConversationMessage.objects.filter(
                conversation_id=conversation_id,
            )
            .order_by(order_field)
            .values_list("role", "content", "created_at")
        )

        try:
            offset_value = max(int(offset), 0)
        except (TypeError, ValueError):
            offset_value = 0

        if offset_value:
            qs = qs[offset_value:]

        try:
            limit_value = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit_value = None
        if limit_value is not None and limit_value > 0:
            qs = qs[:limit_value]

        return [
            {
                "role": role,
                "content": content,
                "created_at": created_at.isoformat() if created_at else None,
            }
            for role, content, created_at in qs
        ]

    def clear_memory(self) -> None:
        """Clear all memory for this agent"""
        _, ConversationMessage = _get_conversation_models()
        conversation_id = self.get_conversation_id()
        ConversationMessage.objects.filter(conversation_id=conversation_id).delete()

    def get_memory_stats(self) -> dict[str, Any]:
        """Get memory statistics for this agent"""
        _, ConversationMessage = _get_conversation_models()
        from django.db.models import Count, Max

        conversation_id = self.get_conversation_id()
        qs = ConversationMessage.objects.filter(conversation_id=conversation_id)

        total_messages = qs.count()

        role_counts = dict(qs.values_list("role").annotate(cnt=Count("id")).values_list("role", "cnt"))

        last_message = qs.aggregate(last=Max("created_at"))["last"]

        return {
            "conversation_id": conversation_id,
            "total_messages": total_messages,
            "role_counts": role_counts,
            "last_message_at": last_message.isoformat() if last_message else None,
            "agent_id": self.agent_id,
            "agent_type": self.agent.agent_type,
        }

    def record_execution(
        self,
        query: str,
        result: str,
        success: bool = True,
        error_message: str = "",
        execution_time_ms: int = None,
        *,
        execution: Any = None,
        execution_id: int = None,
        status: str = None,
        progress: int = None,
        state: dict[str, Any] = None,
        task_id: str = None,
        add_user_message: bool = True,
        add_agent_message: bool = True,
        update_agent_stats: bool = True,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Record agent execution in both memory and execution log.

        ``artifacts`` (optional) is the list of downloadable outputs
        the agent collected during this execution — typically a single
        ``{kind, id, title, download_url, mime_type, status}`` dict per
        report PDF the agent kicked off. They land on the assistant
        message's ``metadata['artifacts']`` so the frontend bubble can
        render a paperclip download icon.
        """
        _, AgentExecution = _get_agent_models()

        if execution is None and execution_id is not None:
            execution = AgentExecution.objects.get(id=execution_id)

        created_new = False
        if execution is None:
            execution = AgentExecution.objects.create(
                agent=self.agent,
                query=query,
                result=result,
                success=success,
                error_message=error_message,
                execution_time_ms=execution_time_ms,
                status=status or "completed",
                progress=progress if progress is not None else 100,
                state=state or {},
                task_id=task_id or "",
            )
            created_new = True

        # Update conversation memory
        if add_user_message and query:
            self.add_user_message(query)

        if add_agent_message and (result or error_message):
            message_content = result if success else f"Error: {error_message}"
            self.add_agent_message(message_content, artifacts=artifacts)

        # Update execution fields when not newly created or extra metadata provided
        update_fields = []

        if not created_new:
            if execution.query != query:
                execution.query = query
                update_fields.append("query")
            if execution.result != result:
                execution.result = result
                update_fields.append("result")
            if execution.success != success:
                execution.success = success
                update_fields.append("success")
            if execution.error_message != error_message:
                execution.error_message = error_message
                update_fields.append("error_message")
            if execution_time_ms is not None and execution.execution_time_ms != execution_time_ms:
                execution.execution_time_ms = execution_time_ms
                update_fields.append("execution_time_ms")
            if status and execution.status != status:
                execution.status = status
                update_fields.append("status")
            if progress is not None and execution.progress != progress:
                execution.progress = progress
                update_fields.append("progress")
            if state is not None and execution.state != state:
                execution.state = state
                update_fields.append("state")
            if task_id is not None and execution.task_id != task_id:
                execution.task_id = task_id
                update_fields.append("task_id")

            if update_fields:
                if "updated_at" not in update_fields:
                    update_fields.append("updated_at")
                execution.save(update_fields=update_fields)

        # Update agent stats
        if update_agent_stats:
            self.agent.execution_count += 1
            self.agent.last_query = query
            self.agent.last_result = result
            self.agent.last_executed = execution.created_at
            self.agent.save(update_fields=["execution_count", "last_query", "last_result", "last_executed"])

        return execution


def get_agent_memory_service(agent_id: str) -> AgentMemoryService:
    """Factory function to get agent memory service"""
    return AgentMemoryService(agent_id)


def create_agent_conversation(agent_id: str, initial_system_message: str = None) -> str:
    """Create a new conversation for an agent"""
    service = AgentMemoryService(agent_id)
    conversation_id = service.get_conversation_id()

    if initial_system_message:
        service.add_system_message(initial_system_message)

    return conversation_id
