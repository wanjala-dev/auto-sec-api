"""Tier 2 #7 — debounced reindex dispatch from domain-data signals.

The workspace-snapshot data adapter (since Tier 2 #5/#6) embeds
30-day donation / recipient / campaign / grant rollups plus current
top-N lists.  When any of those domains change, the snapshot is
stale until the next ``Workspace.save()`` or the nightly beat —
which is too coarse for a workspace that just received a $10k
donation.

This use case is the application-layer entry point the four new
post_save bridges call.  Its job:

1. Resolve a ``workspace_id`` from whatever model instance the
   signal carried.
2. Defer the Celery dispatch until ``transaction.on_commit`` —
   the donation row needs to be visible to other DB connections
   before the reindex worker queries the rollup.  Without this,
   the reindex runs against pre-commit state and ships a stale
   snapshot.  (See ``.claude/rules/celery-tasks.md`` §3.)
3. Debounce per workspace: the first save in a 60-second window
   wins; subsequent saves are dropped because the in-flight
   reindex will already pick up everything saved between then and
   when it runs.

A burst of 1,000 donations therefore produces ONE reindex per
workspace (not 1,000), and the snapshot's content-hash skip
inside the index adapter catches any redundant trip on top of
that.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from components.knowledge.application.ports.commit_hook_port import (
    CommitHookPort,
)
from components.knowledge.application.ports.key_value_cache_port import (
    KeyValueCachePort,
)

logger = logging.getLogger(__name__)

# 60 seconds is the per-workspace debounce window.  Tuned for the
# common case: a paying nonprofit receives a handful of donations
# per minute during a campaign push — one reindex catches all of
# them, snapshot rebuild stays under a second per workspace, and
# the rollup count never lags more than 60s + Celery latency.
DEBOUNCE_SECONDS = 60

# Cache key namespace.  Versioned so a future cache-key format
# change can roll out without colliding with old keys.
_CACHE_KEY_PREFIX = "knowledge:domain_reindex_v1"


def enqueue_reindex_for_workspace(
    workspace_id: str,
    *,
    domain_label: str,
    created: bool = False,
    cache_port: Optional[KeyValueCachePort] = None,
    commit_hook_port: Optional[CommitHookPort] = None,
) -> bool:
    """Debounced per-workspace reindex enqueue — the reusable core.

    Returns True iff a dispatch was scheduled (the debounce lock was
    just acquired); False if the lock was already held or the
    workspace_id was empty.

    Both the post_save use case (Tier 2 #7) and the M2M use case
    (Tier 2 #8) call this so the debounce + on_commit + error-
    swallowing invariants live in exactly one place.

    ``cache_port`` and ``commit_hook_port`` default to the Django
    adapters via their providers — tests inject in-memory fakes to
    keep the application layer framework-free.
    """
    if not workspace_id:
        return False

    cache_port = cache_port or _default_cache_port()
    commit_hook_port = commit_hook_port or _default_commit_hook_port()

    cache_key = f"{_CACHE_KEY_PREFIX}:{workspace_id}"
    if not cache_port.add(cache_key, "1", ttl_seconds=DEBOUNCE_SECONDS):
        logger.debug(
            "knowledge: debounce hit, skipping reindex enqueue "
            "domain=%s workspace_id=%s",
            domain_label,
            workspace_id,
        )
        return False

    commit_hook_port.on_commit(
        lambda: _dispatch(workspace_id, domain_label, created)
    )
    return True


def _default_cache_port() -> KeyValueCachePort:
    from components.knowledge.application.providers.key_value_cache_provider import (
        key_value_cache,
    )

    return key_value_cache()


def _default_commit_hook_port() -> CommitHookPort:
    from components.knowledge.application.providers.commit_hook_provider import (
        commit_hook,
    )

    return commit_hook()


class EnqueueDomainChangeReindexUseCase:
    """Per-domain handler: model save → debounced reindex enqueue."""

    def __init__(self, *, domain_label: str) -> None:
        # ``domain_label`` is purely diagnostic — appears in log lines
        # so operators can tell whether the reindex burst came from
        # donations, recipients, etc.  Does NOT affect the cache key
        # (debounce is per workspace, not per domain — multiple
        # domain saves on the same workspace within the window are
        # one reindex).
        self._domain_label = domain_label

    def execute(self, *, instance: Any, created: bool) -> None:
        workspace_id = _resolve_workspace_id(instance)
        if not workspace_id:
            logger.debug(
                "knowledge: skipping %s reindex enqueue — no workspace_id",
                self._domain_label,
            )
            return
        enqueue_reindex_for_workspace(
            workspace_id,
            domain_label=self._domain_label,
            created=created,
        )


def _dispatch(workspace_id: str, domain_label: str, created: bool) -> None:
    """Run inside ``on_commit`` — the donation/recipient row is now
    visible to other DB connections, so the reindex worker will see
    the latest state."""
    try:
        from components.knowledge.infrastructure.tasks.workspace_index_tasks import (
            reindex_workspace,
        )

        reindex_workspace.delay(workspace_id, False)
        logger.info(
            "knowledge: dispatched reindex domain=%s workspace_id=%s created=%s",
            domain_label,
            workspace_id,
            created,
        )
    except Exception:  # pylint: disable=broad-except
        # Never propagate from a signal handler — the underlying save
        # transaction has already committed and we must not roll it
        # back.  Failure here means the snapshot stays stale until the
        # next change or the nightly beat heals it.
        logger.exception(
            "knowledge: failed to dispatch reindex domain=%s workspace_id=%s",
            domain_label,
            workspace_id,
        )


def _resolve_workspace_id(instance: Any) -> Optional[str]:
    """Best-effort: read ``workspace_id`` or ``workspace.id`` off the
    instance.  Returns the empty string for orphan rows (e.g. a
    Donation with ``workspace_id=NULL`` — possible historically before
    the FK was enforced).
    """
    workspace_id = getattr(instance, "workspace_id", None)
    if workspace_id:
        return str(workspace_id)
    workspace = getattr(instance, "workspace", None)
    if workspace is not None:
        wid = getattr(workspace, "id", None)
        if wid:
            return str(wid)
    return None
