"""ORM adapter for session memory persistence.

Stores extracted facts as JSON in the Agent model's config field
under the key ``session_memory_facts``.  This avoids needing a new
database table — facts are lightweight and scoped per agent.

A future iteration could move to a dedicated model or vector store
for similarity-based fact deduplication.
"""

from __future__ import annotations

import logging

from components.agents.domain.services.session_memory_extractor import (
    ExtractedFact,
    SessionMemory,
)
from components.agents.application.ports.session_memory_port import SessionMemoryPort

logger = logging.getLogger(__name__)

_FACTS_KEY = "session_memory_facts"
_MAX_FACTS = 50  # Cap per workspace+agent_type to prevent unbounded growth


class OrmSessionMemoryAdapter(SessionMemoryPort):
    """Store session memory facts in the Agent config JSON field."""

    def _get_agent(self, workspace_id: str, agent_type: str):
        from infrastructure.persistence.ai.agents.models import Agent

        return Agent.objects.filter(
            workspace_id=workspace_id,
            agent_type=agent_type,
        ).first()

    def load(self, workspace_id: str, agent_type: str) -> SessionMemory:
        agent = self._get_agent(workspace_id, agent_type)
        if not agent or not agent.config:
            return SessionMemory(workspace_id=workspace_id, agent_type=agent_type)

        raw_facts = agent.config.get(_FACTS_KEY, [])
        facts = [
            ExtractedFact(
                fact_id=f.get("fact_id", ""),
                content=f["content"],
                category=f.get("category", "context"),
                confidence=f.get("confidence", 1.0),
                source_conversation_id=f.get("source_conversation_id", ""),
                extracted_at=None,
            )
            for f in raw_facts
            if f.get("content")
        ]
        return SessionMemory(
            workspace_id=workspace_id,
            agent_type=agent_type,
            facts=facts,
            last_updated=agent.updated_at,
        )

    def save_facts(
        self,
        workspace_id: str,
        agent_type: str,
        facts: list[ExtractedFact],
    ) -> None:
        agent = self._get_agent(workspace_id, agent_type)
        if not agent:
            logger.warning(
                "No agent found for workspace=%s agent_type=%s — cannot save session memory",
                workspace_id, agent_type,
            )
            return

        config = agent.config or {}
        existing = config.get(_FACTS_KEY, [])
        existing_contents = {f["content"] for f in existing}

        for fact in facts:
            if fact.content not in existing_contents:
                existing.append({
                    "fact_id": str(fact.fact_id),
                    "content": fact.content,
                    "category": fact.category,
                    "confidence": fact.confidence,
                    "source_conversation_id": fact.source_conversation_id,
                    "extracted_at": (
                        fact.extracted_at.isoformat() if fact.extracted_at else None
                    ),
                })
                existing_contents.add(fact.content)

        # Cap to prevent unbounded growth
        config[_FACTS_KEY] = existing[-_MAX_FACTS:]
        agent.config = config
        agent.save(update_fields=["config", "updated_at"])

    def clear(self, workspace_id: str, agent_type: str) -> None:
        agent = self._get_agent(workspace_id, agent_type)
        if not agent or not agent.config:
            return
        agent.config.pop(_FACTS_KEY, None)
        agent.save(update_fields=["config", "updated_at"])
