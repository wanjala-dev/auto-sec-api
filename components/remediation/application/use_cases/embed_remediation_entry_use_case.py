"""EmbedRemediationEntryUseCase — make a vetted fix retrievable (ADR 0012 P4).

Runs AFTER the entry-gate has admitted a ``RemediationEntry`` (D1). It embeds the
entry into the EXISTING knowledge pgvector store (``ai_embedding_chunks``) via the
knowledge-owned :class:`CorpusChunkIndexPort` — reusing knowledge's embeddings +
store, standing up no parallel vector store. The chunk is stamped with the
retrieval keys the triage advisor later filters on:

    {chunk_type: "remediation_entry", workspace_id, finding_kind, source_type,
     language, title, summary, tags, code, entry_id}

Tenant isolation (D4) begins here: ``workspace_id`` is written into every chunk's
metadata so retrieval can pin ``metadata.workspace_id = <this ws>``. Idempotent: the
chunk is keyed on the entry id (``remediation_entry:<id>``), so re-embedding the
same entry REPLACES the prior chunk in place — never duplicates.

This use case is READ-ONLY with respect to the corpus (it never creates a
``RemediationEntry``); the gate (``RecordRemediationEntryUseCase``) remains the sole
writer (D1). It only makes an already-admitted entry searchable.
"""

from __future__ import annotations

import logging

from components.knowledge.application.ports.corpus_chunk_index_port import (
    CorpusChunkIndexPort,
)
from components.remediation.application.ports.remediation_retrieval_port import (
    REMEDIATION_CHUNK_TYPE,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.domain.services.secret_redactor import redact_secrets

logger = logging.getLogger(__name__)

# Bound the embedded code so a pathological fix never blows the embedding token
# budget. The full raw fix is preserved on the RemediationEntry row (D3); this is
# only the searchable projection.
_MAX_CODE_CHARS = 8_000


def document_key_for(entry_id: str) -> str:
    """Stable, per-entry chunk key — a repeat embed replaces in place (idempotent)."""
    return f"remediation_entry:{entry_id}"


class EmbedRemediationEntryUseCase:
    def __init__(self, *, index: CorpusChunkIndexPort) -> None:
        self._index = index

    def execute(self, entry: RemediationEntry) -> int:
        # Defence-in-depth secret scrub (ADR 0012 P6): redact obvious credentials from
        # the fix code BEFORE it is embedded / carried in chunk metadata, so a live
        # secret never lands in the retrievable corpus (the advisor reads this back as
        # grounding). The entry ROW keeps its raw code (D3 source of truth); this scrubs
        # only the searchable projection. Never log the raw or matched value — a count
        # only (logging.md §4).
        safe_code, redactions = redact_secrets((entry.code or "")[:_MAX_CODE_CHARS])
        if redactions:
            logger.warning(
                "remediation_entry_code_redacted entry_id=%s workspace_id=%s redactions=%d",
                entry.id,
                entry.workspace_id,
                redactions,
            )
        content = self._build_content(entry, safe_code)
        metadata = {
            "chunk_type": REMEDIATION_CHUNK_TYPE,
            "workspace_id": str(entry.workspace_id),
            "finding_kind": entry.finding_kind or "",
            "source_type": entry.source_type or "",
            "language": entry.language or "",
            "title": entry.title or "",
            "summary": entry.summary or "",
            "tags": list(entry.tags),
            # RAW fix text (D3: never rendered HTML), SECRET-SCRUBBED (P6) — carried so
            # retrieval can hand the advisor the prior fix's code without a second DB read.
            "code": safe_code,
            "entry_id": str(entry.id),
            # The DERIVED outcome rating (P5). Retrieval blends this with vector
            # similarity so proven fixes outrank unproven ones; re-embedding on each
            # outcome keeps the ranked rating current.
            "rating": int(entry.score),
        }
        written = self._index.index_chunk(
            document_key=document_key_for(str(entry.id)),
            content=content,
            metadata=metadata,
        )
        logger.info(
            "remediation_entry_embedded entry_id=%s workspace_id=%s finding_kind=%s chunks=%d",
            entry.id,
            entry.workspace_id,
            entry.finding_kind,
            written,
        )
        return written

    @staticmethod
    def _build_content(entry: RemediationEntry, safe_code: str) -> str:
        """Compose the searchable text: the finding context + the (scrubbed) fix.

        This is what a triage query (the error message / evidence) is matched
        against, so it leads with the human-readable finding context and follows
        with the fix code. ``safe_code`` is the secret-scrubbed projection (P6).
        """
        parts = [
            f"Remediation for {entry.finding_kind} finding.",
            entry.title or "",
            entry.summary or "",
            f"Fix ({entry.language or 'code'}):",
            safe_code,
        ]
        return "\n".join(p for p in parts if p and str(p).strip())
