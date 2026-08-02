"""Event handler — index a published WritingDraft into the knowledge vector store.

Sibling of ``rag_index_newsletter_handler``. Fires on
``WritingDraftPublished``; surfaces drafts in the agent's
``retrieve_past_writing`` tool so a thank-you-letter agent can echo
phrasing the org has used before.

Gated by the same ``feature.writing_rag_indexing`` flag as the
newsletter handler — one toggle controls the whole writing corpus.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from components.content.domain.events.writing_draft_published_event import (
    WritingDraftPublished,
)

logger = logging.getLogger(__name__)


_FLAG_KEY = "feature.writing_rag_indexing"


def on_writing_draft_published_index_rag(event: WritingDraftPublished) -> None:
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )

    is_feature_enabled = get_feature_flags_provider().is_feature_enabled

    workspace_id = str(event.workspace_id)
    if not is_feature_enabled(_FLAG_KEY, workspace_id=workspace_id):
        logger.info(
            "writing_draft.rag_index_skipped_flag_off draft_id=%s workspace_id=%s",
            event.draft_id,
            workspace_id,
        )
        return

    # Resolve the draft repository through its provider — the handler reads
    # the draft + stamps its indexed marker through the WritingDraft ports,
    # never the ORM (the application layer stays ORM-free).
    from components.content.application.providers.writing_draft_repository_provider import (
        get_writing_draft_repository_provider,
    )
    from components.knowledge.application.providers.knowledge_text_ingest_provider import (
        KnowledgeTextIngestProvider,
    )

    repo = get_writing_draft_repository_provider().repository()
    row = repo.get(draft_id=event.draft_id)
    if row is None:
        logger.warning("writing_draft.rag_index_missing_row draft_id=%s", event.draft_id)
        return

    corpus = _build_corpus(row)
    if not corpus.strip():
        logger.info("writing_draft.rag_index_empty_corpus draft_id=%s", row.id)
        return

    document_key = f"writing_draft:{row.workspace_id}:{row.id}"
    port = KnowledgeTextIngestProvider().build_port()
    metadata = {
        "source": "writing_draft",
        "workspace_id": str(row.workspace_id),
        "draft_id": str(row.id),
        "title": row.title or "",
        "kind": row.kind,
        "published_at": row.updated_at.isoformat() if row.updated_at else "",
        "status": "active",
        "privacy": "private",
    }

    try:
        chunks = port.index_text(
            text=corpus,
            document_key=document_key,
            metadata=metadata,
        )
    except Exception:
        logger.exception("writing_draft.rag_index_failed draft_id=%s", row.id)
        return

    repo.stamp_rag_indexed(
        draft_id=row.id,
        document_key=document_key,
        indexed_at=datetime.now(UTC),
    )
    logger.info(
        "writing_draft.rag_indexed draft_id=%s kind=%s chunks=%d",
        row.id,
        row.kind,
        chunks,
    )


def _build_corpus(row) -> str:
    import re

    title = (row.title or "").strip()
    html = row.body_html or ""
    body = re.sub(r"<[^>]+>", " ", html)
    body = re.sub(r"\s+", " ", body).strip()

    parts: list[str] = []
    if title:
        parts.append(f"Title: {title}")
    parts.append(f"Kind: {row.kind}")
    if body:
        parts.append(f"Body:\n{body}")
    return "\n\n".join(parts)
