"""
LangChain implementation of AgentMemoryPort.

Bridges the framework-agnostic ``AgentMemoryPort`` to LangChain's
``ConversationBufferMemory`` and the existing ``AgentMemoryService``.

To swap to LlamaIndex, create ``infrastructure/adapters/llamaindex/memory_adapter.py``
implementing the same port with ``ChatMemoryBuffer``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from components.agents.application.ports.agent_memory_port import (
    AgentMemoryPort,
    MemoryHandle,
    MemoryMessage,
    MemoryStats,
)


class LangChainMemoryAdapter(AgentMemoryPort):
    """Adapts LangChain memory subsystem to AgentMemoryPort."""

    def _get_memory_service(self):
        """Lazy import to avoid pulling the full model graph at module level."""
        from components.agents.infrastructure.adapters.langchain.memory_service import (
            AgentMemoryService,
            get_agent_memory_service,
        )
        return get_agent_memory_service()

    # ------------------------------------------------------------------
    # Port implementation
    # ------------------------------------------------------------------

    def get_or_create_conversation_id(
        self,
        agent_id: str,
        *,
        thread_id: Optional[str] = None,
    ) -> str:
        svc = self._get_memory_service()
        # AgentMemoryService.get_conversation_id expects an agent-like object
        # with config dict; we simulate that minimal interface.
        class _Stub:
            def __init__(self, aid, tid):
                self.config = {"agent_id": aid}
                if tid:
                    self.config["thread_id"] = tid
        stub = _Stub(agent_id, thread_id)
        return svc.get_conversation_id(stub)

    def build_memory(
        self,
        conversation_id: str,
        *,
        memory_type: str = "buffer",
        max_messages: Optional[int] = None,
        max_message_chars: Optional[int] = None,
        max_total_chars: Optional[int] = None,
        system_message: Optional[str] = None,
        **kwargs: Any,
    ) -> MemoryHandle:
        svc = self._get_memory_service()
        memory_obj = svc.get_memory(
            conversation_id=conversation_id,
            memory_type=memory_type,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
            system_message=system_message,
        )
        return MemoryHandle(
            conversation_id=conversation_id,
            _impl=memory_obj,
        )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        svc = self._get_memory_service()
        if role == "human":
            svc.add_user_message(conversation_id, content)
        elif role == "ai":
            svc.add_agent_message(conversation_id, content)
        elif role == "system":
            svc.add_system_message(conversation_id, content)

    def get_history(
        self,
        conversation_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MemoryMessage]:
        svc = self._get_memory_service()
        raw = svc.get_conversation_history(
            conversation_id,
            limit=limit,
            offset=offset,
        )
        return [
            MemoryMessage(
                role=msg.get("role", "unknown"),
                content=msg.get("content", ""),
                created_at=str(msg.get("created_at", "")),
            )
            for msg in raw
        ]

    def record_execution(
        self,
        agent_id: str,
        conversation_id: str,
        *,
        query: str,
        response: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        svc = self._get_memory_service()
        svc.record_execution(
            agent_id=agent_id,
            conversation_id=conversation_id,
            query=query,
            response=response,
            metadata=metadata or {},
        )

    def get_stats(self, conversation_id: str) -> MemoryStats:
        svc = self._get_memory_service()
        raw = svc.get_memory_stats(conversation_id)
        return MemoryStats(
            total_messages=raw.get("total", 0),
            human_messages=raw.get("human", 0),
            ai_messages=raw.get("ai", 0),
            system_messages=raw.get("system", 0),
            last_activity=str(raw.get("last_activity", "")),
        )

    def clear(self, conversation_id: str) -> None:
        svc = self._get_memory_service()
        if hasattr(svc, "clear"):
            svc.clear(conversation_id)
