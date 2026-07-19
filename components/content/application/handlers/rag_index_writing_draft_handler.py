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
from datetime import datetime, timezone

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

    from infrastructure.persistence.content.models import WritingDraft
    from components.knowledge.application.providers.knowledge_text_ingest_provider import (
        KnowledgeTextIngestProvider,
    )

    row = (
        WritingDraft.objects.filter(pk=event.draft_id)
        .only(
            "id",
            "workspace_id",
            "title",
            "body_html",
            "kind",
            "updated_at",
            "metadata",
        )
        .first()
    )
    if row is None:
        logger.warning(
            "writing_draft.rag_index_missing_row draft_id=%s", event.draft_id
        )
        return

    corpus = _build_corpus(row)
    if not corpus.strip():
        logger.info(
            "writing_draft.rag_index_empty_corpus draft_id=%s", row.id
        )
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
    except Exception:  # noqa: BLE001 — must not fail the publish flow
        logger.exception("writing_draft.rag_index_failed draft_id=%s", row.id)
        return

    stamped_metadata = dict(row.metadata or {})
    stamped_metadata["rag_indexed_at"] = datetime.now(timezone.utc).isoformat()
    stamped_metadata["rag_document_key"] = document_key
    WritingDraft.objects.filter(pk=row.pk).update(metadata=stamped_metadata)
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
