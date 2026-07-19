"""Celery tasks that drive the workspace index pipeline.

Two public tasks:

- ``reindex_workspace(workspace_id, force=False)`` — idempotent per-workspace
  reindex.  Enqueued from the ``post_save`` signal bridge and from the
  nightly refresh.  Content-hash skip is inside the adapter, so callers
  don't need to decide whether a workspace actually changed.

- ``reindex_all_workspaces(force=False)`` — beat-scheduled fan-out.  Walks
  active workspaces and enqueues a ``reindex_workspace`` task for each.
  Used both for drift correction (nightly) and one-shot backfills via the
  management command.

Retry policy follows the celery-tasks rule: explicit name, bind=True,
exponential backoff with jitter, capped.  Idempotency is guaranteed by
the adapter's wipe-and-replace + content-hash skip.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import InterfaceError, OperationalError

logger = logging.getLogger(__name__)

# Transient errors worth retrying. Programming errors (TypeError, KeyError,
# ValueError from a bad payload, etc.) must fail loudly, not exhaust 5 retries
# (celery-tasks skill §3). OpenAI / langchain transient errors are imported
# defensively so the task module still loads if the SDK layout shifts.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    OperationalError,
    InterfaceError,
)

try:  # pragma: no cover - import shape depends on installed openai version
    import openai as _openai

    _RETRYABLE_EXCEPTIONS = _RETRYABLE_EXCEPTIONS + (
        _openai.APITimeoutError,
        _openai.RateLimitError,
        _openai.APIConnectionError,
    )
except (ImportError, AttributeError):  # pragma: no cover
    pass


@shared_task(
    name="components.knowledge.workspace_index.reindex_workspace",
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=120,
    time_limit=180,
    # Per-worker work bound. With the nightly fanout dispatching
    # every active workspace in a tight loop and the content-hash
    # skip costing almost nothing on unchanged workspaces, the bound
    # exists primarily to protect the broker + the embedding API
    # from a runaway signal-bridge cascade. ``20/s`` per worker means
    # a two-worker pool handles ~40 reindexes per second — well above
    # any organic burst even on the busiest demo workspace, while
    # capping the worst case at a known ceiling. Tier 3 #14 audit.
    rate_limit="20/s",
)
def reindex_workspace(self, workspace_id: str, force: bool = False) -> dict:
    """Reindex a single workspace.  Idempotent; safe to retry.

    Returns a plain dict so Flower / result backends don't choke on the
    frozen dataclass.  Fields mirror ``ReindexResult``.
    """
    from components.knowledge.application.providers.workspace_index_provider import (
        workspace_index,
    )

    logger.info(
        "reindex_workspace started workspace_id=%s force=%s", workspace_id, force
    )
    try:
        adapter = workspace_index()
        result = adapter.reindex(workspace_id, force=force)
    except _RETRYABLE_EXCEPTIONS as exc:
        # Transient — DB blip, network, OpenAI timeout/rate-limit. Retry with
        # the configured exponential backoff + jitter.
        logger.exception(
            "reindex_workspace transient failure workspace_id=%s", workspace_id
        )
        raise self.retry(exc=exc) from exc
    except Exception:
        # Non-transient (programming/validation/4xx-shaped) errors must fail
        # loudly — retrying 5× wastes work and hides the bug (celery-tasks §3).
        logger.exception(
            "reindex_workspace non-retryable failure workspace_id=%s", workspace_id
        )
        raise

    payload = {
        "status": result.status,
        "workspace_id": result.workspace_id,
        "chunks_written": result.chunks_written,
        "content_hash": result.content_hash,
        "reason": result.reason,
    }
    logger.info(
        "reindex_workspace completed workspace_id=%s status=%s chunks=%s",
        workspace_id,
        result.status,
        result.chunks_written,
    )
    return payload


@shared_task(
    name="components.knowledge.workspace_index.reindex_all_workspaces",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=600,
    time_limit=900,
)
def reindex_all_workspaces(self, force: bool = False) -> dict:
    """Fan out ``reindex_workspace`` for every active workspace.

    Enqueued from Celery Beat (nightly) and from the management command.
    Returns a summary dict listing how many tasks were dispatched.
    """
    from infrastructure.persistence.workspaces.models import Workspace

    logger.info("reindex_all_workspaces started force=%s", force)

    # Stream IDs with iterator(chunk_size=500) so the fan-out doesn't
    # materialise every workspace ID into memory at once. At hundreds
    # of workspaces it doesn't matter; at tens of thousands it does,
    # and shipping the iterator now means we don't have to re-architect
    # this task once growth hits.  Tier 3 #14 audit (2026-06-11).
    queryset = (
        Workspace.objects.filter(is_active=True)
        .order_by("id")
        .values_list("id", flat=True)
    )

    dispatched = 0
    total_seen = 0
    for workspace_id in queryset.iterator(chunk_size=500):
        total_seen += 1
        try:
            reindex_workspace.delay(str(workspace_id), force)
            dispatched += 1
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Failed to enqueue reindex_workspace for %s", workspace_id
            )

        # Log progress every 100 dispatches so an operator tailing
        # logs can see the fan-out making progress, not just
        # "started" / "completed" lines minutes apart. Cheap because
        # the integer division branch is hit once per 100 rows.
        if total_seen % 100 == 0:
            logger.info(
                "reindex_all_workspaces progress dispatched=%s total_seen=%s",
                dispatched,
                total_seen,
            )

    logger.info(
        "reindex_all_workspaces completed dispatched=%s total_seen=%s",
        dispatched,
        total_seen,
    )
    return {"dispatched": dispatched, "total_active": total_seen}
