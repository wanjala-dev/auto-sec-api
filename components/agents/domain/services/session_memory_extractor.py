"""Session memory extraction — distill conversations into durable facts.

After N turns (or on demand), the extractor summarizes the conversation
into a set of structured facts that persist across sessions.  This gives
workspace AI agents "memory" that survives conversation boundaries.

Pure domain service — no ORM, no LangChain, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ExtractedFact:
    """A single durable fact extracted from a conversation."""

    fact_id: UUID
    content: str
    category: str  # "preference", "context", "decision", "entity", "workflow"
    confidence: float = 1.0
    source_conversation_id: str = ""
    extracted_at: datetime | None = None

    @classmethod
    def create(
        cls,
        content: str,
        category: str,
        *,
        confidence: float = 1.0,
        source_conversation_id: str = "",
    ) -> ExtractedFact:
        return cls(
            fact_id=uuid4(),
            content=content,
            category=category,
            confidence=confidence,
            source_conversation_id=source_conversation_id,
            extracted_at=datetime.utcnow(),
        )


@dataclass(frozen=True)
class SessionMemory:
    """Durable memory for a workspace agent, composed of extracted facts."""

    workspace_id: str
    agent_type: str
    facts: list[ExtractedFact] = field(default_factory=list)
    last_updated: datetime | None = None

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    def as_context_string(self, *, max_facts: int = 20) -> str:
        """Format facts into a string suitable for prompt injection."""
        if not self.facts:
            return ""
        lines = [
            f"- [{f.category}] {f.content}"
            for f in self.facts[:max_facts]
        ]
        return (
            "## Remembered context from previous conversations\n"
            + "\n".join(lines)
        )


# ── Extraction prompt template ──────────────────────────────────────

EXTRACTION_PROMPT = """You are analysing a conversation between a workspace admin and an AI assistant.

Extract the most important DURABLE FACTS from this conversation — things that would be useful to remember in future conversations. Focus on:

1. **preferences** — how the user likes things done
2. **context** — key business context, names, roles, relationships
3. **decisions** — choices that were made and why
4. **entities** — important projects, budgets, campaigns, people mentioned
5. **workflows** — processes or patterns the user follows

Return a JSON array of objects, each with:
- "content": the fact (1-2 sentences)
- "category": one of "preference", "context", "decision", "entity", "workflow"
- "confidence": 0.0-1.0 how confident you are this is worth remembering

Only include facts that would be useful ACROSS conversations. Skip ephemeral details.
Maximum 10 facts per extraction.

Conversation:
{conversation}

Extracted facts (JSON array):"""


def build_extraction_prompt(conversation_text: str) -> str:
    """Build the LLM prompt for fact extraction."""
    return EXTRACTION_PROMPT.format(conversation=conversation_text)
