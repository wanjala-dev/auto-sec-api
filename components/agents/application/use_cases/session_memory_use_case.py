"""Use case: extract durable facts from a conversation and persist them.

Called after a conversation reaches a threshold of turns, or on demand
via the API / management command.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from components.agents.domain.services.session_memory_extractor import (
    ExtractedFact,
    SessionMemory,
    build_extraction_prompt,
)
from components.agents.application.ports.session_memory_port import SessionMemoryPort
from components.knowledge.application.ports.llm_port import LlmPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractSessionMemoryCommand:
    workspace_id: str
    agent_type: str
    conversation_text: str
    conversation_id: str = ""


@dataclass(frozen=True)
class ExtractSessionMemoryResult:
    facts_extracted: int
    facts: list[ExtractedFact]


class ExtractSessionMemoryUseCase:
    """Orchestrate: build prompt → LLM extract → parse → persist."""

    # Only extract when conversation has at least this many messages
    MIN_MESSAGES_FOR_EXTRACTION = 6

    def __init__(
        self,
        *,
        llm: LlmPort,
        session_memory: SessionMemoryPort,
    ) -> None:
        self._llm = llm
        self._session_memory = session_memory

    def execute(self, command: ExtractSessionMemoryCommand) -> ExtractSessionMemoryResult:
        prompt = build_extraction_prompt(command.conversation_text)

        try:
            response = self._llm.invoke(prompt)
            raw_facts = self._parse_facts(response.content)
        except Exception:
            logger.exception("Session memory extraction failed for workspace=%s", command.workspace_id)
            return ExtractSessionMemoryResult(facts_extracted=0, facts=[])

        facts = [
            ExtractedFact.create(
                content=f["content"],
                category=f.get("category", "context"),
                confidence=float(f.get("confidence", 0.8)),
                source_conversation_id=command.conversation_id,
            )
            for f in raw_facts
            if f.get("content")
        ]

        if facts:
            self._session_memory.save_facts(
                command.workspace_id,
                command.agent_type,
                facts,
            )

        return ExtractSessionMemoryResult(
            facts_extracted=len(facts),
            facts=facts,
        )

    def load_memory(self, workspace_id: str, agent_type: str) -> SessionMemory:
        """Load existing session memory for prompt injection."""
        return self._session_memory.load(workspace_id, agent_type)

    @staticmethod
    def _parse_facts(llm_output: str) -> list[dict[str, Any]]:
        """Parse the LLM JSON output into a list of fact dicts."""
        text = llm_output.strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            logger.warning("Failed to parse extraction output as JSON")
        return []
