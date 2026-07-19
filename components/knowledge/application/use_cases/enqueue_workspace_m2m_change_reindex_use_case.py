"""Tier 2 #8 — reindex on Workspace M2M relationship changes.

``Workspace.post_save`` does NOT fire when a many-to-many field
changes (categories / tags / operations / subcategories /
contribution_means).  ``ws.tags.add(new_tag)`` writes to the through
table only, leaving the Workspace row untouched.  Pre-Tier-2-#8 a
renamed-via-replacement category lived stale in the embedding until
the next direct ``Workspace.save()``.

This use case handles ``m2m_changed`` signals from those through
tables, resolves which Workspace was affected (forward direction
when the user wrote ``ws.tags.add(tag)``; reverse direction when
the user wrote ``tag.workspaces.add(ws)``), and reuses the
Tier 2 #7 debounce helper so a burst of M2M edits within the 60s
window only triggers ONE reindex per workspace.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #8.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Set

from components.knowledge.application.use_cases.enqueue_domain_change_reindex_use_case import (
    enqueue_reindex_for_workspace,
)

logger = logging.getLogger(__name__)

# Actions we react to — only post-* because we want the through-table
# write to be visible to the snapshot adapter when the reindex worker
# runs.  pre_* would race the row.
_INTERESTING_ACTIONS = frozenset({"post_add", "post_remove", "post_clear"})


class EnqueueWorkspaceM2mChangeReindexUseCase:
    """Handler for ``m2m_changed`` on Workspace M2M through tables."""

    def __init__(self, *, m2m_label: str) -> None:
        # ``m2m_label`` is diagnostic only — names which M2M
        # ("categories" / "tags" / etc.) in the log line so operators
        # can attribute a reindex burst.
        self._m2m_label = m2m_label

    def execute(
        self,
        *,
        action: str,
        instance: Any,
        pk_set: Set[Any] | None,
        reverse: bool,
    ) -> None:
        if action not in _INTERESTING_ACTIONS:
            return

        workspace_ids = _resolve_workspace_ids(
            instance=instance,
            pk_set=pk_set,
            reverse=reverse,
        )
        for workspace_id in workspace_ids:
            enqueue_reindex_for_workspace(
                workspace_id,
                domain_label=f"workspace_m2m:{self._m2m_label}",
                created=False,
            )


def _resolve_workspace_ids(
    *, instance: Any, pk_set: Set[Any] | None, reverse: bool
) -> Iterable[str]:
    """Pull workspace_ids out of an ``m2m_changed`` payload.

    Forward direction (``ws.tags.add(tag)``): ``instance`` is the
    Workspace, ``pk_set`` is the tag ids — we reindex one workspace.

    Reverse direction (``tag.workspaces.add(ws)``): ``instance`` is
    the Tag, ``pk_set`` is the workspace ids — we reindex each
    workspace in ``pk_set``.

    ``post_clear`` carries ``pk_set=None`` because Django doesn't
    know which rows existed before the clear; we fall back to the
    instance side, which for a reverse-clear leaves us unable to
    name affected workspaces.  That's acceptable: clear is rare and
    the nightly beat heals it.
    """
    if reverse:
        # Reverse: instance is the related model; pk_set lists
        # workspaces.  For post_clear we don't have the ids — return
        # empty (intentional best-effort).
        if not pk_set:
            return ()
        return tuple(str(pk) for pk in pk_set if pk)

    # Forward: instance is the Workspace.
    ws_id = getattr(instance, "id", None) or getattr(instance, "pk", None)
    if ws_id:
        return (str(ws_id),)
    return ()
