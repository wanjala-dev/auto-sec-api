"""Celery task: embed an admitted RemediationEntry into the retrievable corpus (ADR 0012 P4).

The driving adapter for :class:`EmbedRemediationEntryUseCase`. Dispatched
after-commit by the capture handler once the entry-gate has ADMITTED an entry (D1),
so the (slow) embedding call happens off the request/reconcile path.

Celery discipline (``.claude/rules/performance.md`` §7, celery-tasks skill): it
receives IDs, not objects; loads the entry through the workspace-scoped STORE PORT
(never the ``RemediationEntry`` ORM model — that stays exclusive to the sole-writer
repository, D1); and is idempotent — re-embedding the same entry replaces its chunk
in place, so a retry or a duplicate dispatch is harmless.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="remediation.embed_remediation_entry", soft_time_limit=120, time_limit=180)
def embed_remediation_entry(entry_id: str, workspace_id: str) -> int:
    """Embed the vetted fix ``entry_id`` (in ``workspace_id``) so triage can retrieve it.

    Returns the number of chunks written (0 when the entry is absent — e.g. revoked
    between dispatch and run). Safe to enqueue repeatedly (idempotent by entry id)."""
    from uuid import UUID

    from components.remediation.application.providers.remediation_provider import (
        build_embed_remediation_entry_use_case,
        build_remediation_service,
    )

    logger.info("embed_remediation_entry started entry_id=%s workspace_id=%s", entry_id, workspace_id)

    try:
        service = build_remediation_service()
        entry = service.get(entry_id=UUID(str(entry_id)), workspace_id=UUID(str(workspace_id)))
    except (ValueError, TypeError):
        logger.warning("embed_remediation_entry bad ids entry_id=%s workspace_id=%s", entry_id, workspace_id)
        return 0

    if entry is None:
        # The entry is gone (revoked / never existed for this workspace) — nothing
        # to embed. Workspace-scoped ``get`` also means a foreign id resolves to None
        # (tenant isolation), so this never embeds another tenant's entry.
        logger.info("embed_remediation_entry entry_absent entry_id=%s workspace_id=%s", entry_id, workspace_id)
        return 0

    written = build_embed_remediation_entry_use_case().execute(entry)
    logger.info(
        "embed_remediation_entry completed entry_id=%s workspace_id=%s chunks=%d",
        entry_id,
        workspace_id,
        written,
    )
    return written
