"""Event handler — index a sent newsletter into the knowledge vector store.

Mirrors ``components/reports/application/handlers/rag_index_handler.py``
so the writing_agent's ``retrieve_past_newsletters`` tool can surface
prior issues during agentic-RAG newsletter composition.

Subscribed to ``NewsletterSent`` via the Celery publisher → runs as its
own task with fault isolation from the dispatch path. If indexing
fails, we log and move on — the backfill management command (or the
next regenerate) retries.

Gated by ``feature.writing_rag_indexing`` so prod embedding spend can
be evaluated per workspace before going wide. The flag defaults to
True in dev; prod has a global-disable rule that's flipped on per
paying workspace.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from components.content.domain.events.newsletter_sent_event import NewsletterSent

logger = logging.getLogger(__name__)


_FLAG_KEY = "feature.writing_rag_indexing"


def on_newsletter_sent_index_rag(event: NewsletterSent) -> None:
    """Build a text corpus for the sent newsletter + write it to the
    workspace vector store."""

    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    is_feature_enabled = get_feature_flags_provider().is_feature_enabled

    workspace_id = str(event.workspace_id)
    if not is_feature_enabled(_FLAG_KEY, workspace_id=workspace_id):
        logger.info(
            "newsletter.rag_index_skipped_flag_off newsletter_id=%s workspace_id=%s",
            event.newsletter_id,
            workspace_id,
        )
        return

    # Lazy imports — keep the module light at app boot.
    from infrastructure.persistence.content.models import Newsletter
    from components.knowledge.application.providers.knowledge_text_ingest_provider import (
        KnowledgeTextIngestProvider,
    )

    row = (
        Newsletter.objects.filter(pk=event.newsletter_id)
        .only(
            "id",
            "workspace_id",
            "title",
            "subject",
            "preheader",
            "content_html",
            "period_start",
            "period_end",
            "sent_at",
            "metadata",
        )
        .first()
    )
    if row is None:
        logger.warning(
            "newsletter.rag_index_missing_row newsletter_id=%s", event.newsletter_id
        )
        return

    corpus = _build_corpus(row)
    if not corpus.strip():
        logger.info("newsletter.rag_index_empty_corpus newsletter_id=%s", row.id)
        return

    document_key = _document_key(row)
    port = KnowledgeTextIngestProvider().build_port()

    metadata = {
        "source": "newsletter",
        "workspace_id": str(row.workspace_id),
        "newsletter_id": str(row.id),
        "title": row.title or "",
        "sent_at": row.sent_at.isoformat() if row.sent_at else "",
        "period_start": row.period_start.isoformat() if row.period_start else "",
        "period_end": row.period_end.isoformat() if row.period_end else "",
        "status": "active",
        "privacy": "private",
    }

    try:
        chunks = port.index_text(
            text=corpus,
            document_key=document_key,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 — embedding outage must not fail the send
        logger.exception("newsletter.rag_index_failed newsletter_id=%s", row.id)
        return

    # Stamp the indexed-at timestamp on the row's metadata JSONField. The
    # newsletter table has no dedicated column — the backfill command
    # uses this stamp to skip already-indexed rows.
    stamped_metadata = dict(row.metadata or {})
    stamped_metadata["rag_indexed_at"] = datetime.now(timezone.utc).isoformat()
    stamped_metadata["rag_document_key"] = document_key
    Newsletter.objects.filter(pk=row.pk).update(metadata=stamped_metadata)
    logger.info(
        "newsletter.rag_indexed newsletter_id=%s chunks=%d", row.id, chunks
    )


def _document_key(row) -> str:
    """Stable key — scoped by workspace + newsletter id so a regenerated
    AI draft replaces the same chunks instead of duplicating them."""

    return f"newsletter:{row.workspace_id}:{row.id}"


def _build_corpus(row) -> str:
    """Flatten the newsletter into plain text suitable for chunking.

    Keeps the editorial parts (title / subject / preheader / HTML body)
    + the period the newsletter covered, so retrieval over "what did we
    say about Q3?" returns both the prose and the time window.
    """

    import re

    title = (row.title or "").strip()
    subject = (row.subject or "").strip()
    preheader = (row.preheader or "").strip()
    html = row.content_html or ""
    # Drop tags + collapse whitespace. The chunker downstream tokenises
    # plain text, so we don't gain anything by keeping markup.
    body = re.sub(r"<[^>]+>", " ", html)
    body = re.sub(r"\s+", " ", body).strip()

    parts: list[str] = []
    if title:
        parts.append(f"Title: {title}")
    if subject and subject != title:
        parts.append(f"Subject: {subject}")
    if preheader:
        parts.append(f"Preheader: {preheader}")
    if row.period_start and row.period_end:
        parts.append(
            f"Period: {row.period_start.isoformat()} to {row.period_end.isoformat()}"
        )
    if body:
        parts.append(f"Body:\n{body}")
    return "\n\n".join(parts)
