"""Use case: persist AI-assist provenance onto the artifact (task #22).

Henry: "put all the ai sources in the details drawer so the user can see
which sources were cited when ai assist ran". The ask-ai response carried
``source_chunks`` + ``faithfulness`` but only in memory — a reload lost
them. This records a trimmed, durable ``ai_provenance`` document under the
artifact's metadata (server-written key; the draft repo preserves it
against full-metadata saves), so any Communications editor's Details
drawer can show what the last AI assist drew on.

Trimming: chunks store an excerpt, not the full retrieved text — the
drawer shows WHERE the content came from; the knowledge store keeps the
text itself.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from components.content.application.ports.newsletter_store_port import (
    NewsletterStorePort,
)
from components.content.application.ports.writing_draft_store_port import (
    WritingDraftStorePort,
)

_MAX_CHUNKS = 12
_EXCERPT_CHARS = 280
_PROMPT_CHARS = 500

PROVENANCE_KEY = "ai_provenance"


def build_provenance(*, result: dict, prompt: str, now: datetime.datetime) -> dict:
    """Trim an ask-ai result into the durable provenance shape."""
    chunks = []
    for chunk in (result.get("source_chunks") or [])[:_MAX_CHUNKS]:
        if not isinstance(chunk, dict):
            continue
        chunks.append(
            {
                "section": str(chunk.get("section") or ""),
                "section_title": str(chunk.get("section_title") or ""),
                "score": chunk.get("score"),
                "excerpt": str(chunk.get("content") or "")[:_EXCERPT_CHARS],
            }
        )
    faithfulness = result.get("faithfulness")
    return {
        "generated_at": now.isoformat(),
        "prompt": (prompt or "")[:_PROMPT_CHARS],
        "agent_type": str(result.get("agent_type") or ""),
        "source_chunks": chunks,
        "faithfulness": faithfulness if isinstance(faithfulness, dict) else {},
    }


@dataclass
class RecordAiProvenanceUseCase:
    draft_store: WritingDraftStorePort
    newsletter_store: NewsletterStorePort

    def record_for_draft(self, *, draft_id: UUID, result: dict, prompt: str, now: datetime.datetime) -> dict:
        provenance = build_provenance(result=result, prompt=prompt, now=now)
        self.draft_store.merge_metadata_key(draft_id=draft_id, key=PROVENANCE_KEY, value=provenance)
        return provenance

    def record_for_newsletter(self, *, newsletter_id: UUID, result: dict, prompt: str, now: datetime.datetime) -> dict:
        provenance = build_provenance(result=result, prompt=prompt, now=now)
        self.newsletter_store.merge_metadata_key(newsletter_id=newsletter_id, key=PROVENANCE_KEY, value=provenance)
        return provenance
