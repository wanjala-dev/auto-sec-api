"""Dual-write bridge: every column write also sets ``workflow_status`` (ADR 0030 P1).

ONE seam catches every write path — the finding handler, the task API, the
kanban sync, ``move_task_to_board``, the specialist moves, and every seeder —
without touching any of them:

- ``Column`` pre_save: a column with no ``workflow_status`` resolves one from
  its title through the ONE canonical vocabulary
  (``components/project/domain/workflow_status_vocabulary.py`` — the same
  mapping the 0008 backfill uses), lazily seeding the team's canonical six
  and creating a LOGGED team-local ``started`` status for an unknown title.
- ``Task`` pre_save: the task mirrors ``column.workflow_status`` — column
  NULL means mirror NULL. A save that does not touch the column and already
  carries a mirror is left alone (zero extra queries on the hot paths).
- post_save (both models): Django silently drops fields a pre_save receiver
  sets when the save named ``update_fields`` without them (the specialist
  move saves ``update_fields=["metadata", "updated_at", "column"]``). When
  that happens AND the mirror actually changed, one targeted UPDATE persists
  it. Full saves and creates never pay this.

The one write path signals cannot catch is batch-move's ``bulk_update`` —
Django fires no signals there, so that repository carries the mirror
explicitly (``batch_move_tasks_repository.py``).

Failure posture: in P1 ``Column`` is still authoritative for every read, so a
mirror-sync failure must never break a task write. Resolution errors are
logged loudly (``logger.exception``) and the save proceeds — the NULL-heal
path picks the row up on its next save, and the 0008 backfill semantics are
re-runnable if a sweep is ever needed.

Registered from ``components/project/cli/apps.py`` ``ready()`` via explicit
``connect`` + ``dispatch_uid`` (repo convention: signal bridges, never
``@receiver``).
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save

from components.project.domain.workflow_status_vocabulary import (
    CANONICAL_STATUSES,
    FALLBACK_CATEGORY,
    resolve_status_name_for_column_title,
)

logger = logging.getLogger(__name__)

#: Stash for "what the row's mirror was before pre_save rewrote it" — the
#: post_save receiver compares against it to decide whether a partial save
#: dropped a real change.
_PRESYNC_ATTR = "_workflow_status_id_before_sync"

_MIRROR_FIELDS = frozenset({"workflow_status", "workflow_status_id"})
_TASK_COLUMN_FIELDS = frozenset({"column", "column_id"})


def ensure_team_workflow_statuses(*, team_id, workspace_id) -> dict[str, int]:
    """Return the team's canonical status ids by name, creating any missing.

    One SELECT in the steady state; ``get_or_create`` (backed by the
    ``uniq_workflow_status_name_per_team`` constraint) keeps concurrent
    seeding atomic — the loser re-reads instead of duplicating.
    """
    from infrastructure.persistence.project.models import WorkflowStatus

    canonical_names = [name for name, _category, _order in CANONICAL_STATUSES]
    existing = dict(
        WorkflowStatus.objects.filter(team_id=team_id, workspace_id=workspace_id, name__in=canonical_names).values_list(
            "name", "id"
        )
    )
    for name, category, order in CANONICAL_STATUSES:
        if name in existing:
            continue
        status, _created = WorkflowStatus.objects.get_or_create(
            team_id=team_id,
            workspace_id=workspace_id,
            name=name,
            defaults={"category": category, "order": order},
        )
        existing[name] = status.id
    return existing


def resolve_workflow_status_id_for_column_title(*, team_id, workspace_id, title) -> int | None:
    """The runtime wrapper around the canonical title mapping.

    Canonical/aliased titles land on the team's canonical status; an unknown
    title mints a team-local ``started`` status AFTER the canonical set and
    logs the divergence (mirroring the 0008 backfill's "exceptions logged").
    """
    from django.db.models import Max

    from infrastructure.persistence.project.models import WorkflowStatus

    canonical = ensure_team_workflow_statuses(team_id=team_id, workspace_id=workspace_id)
    canonical_name = resolve_status_name_for_column_title(title)
    if canonical_name is not None:
        return canonical[canonical_name]

    local_name = (title or "").strip()
    if not local_name:
        return None
    next_order = (
        WorkflowStatus.objects.filter(team_id=team_id, workspace_id=workspace_id).aggregate(max_order=Max("order"))[
            "max_order"
        ]
        or 0
    ) + 1
    status, created = WorkflowStatus.objects.get_or_create(
        team_id=team_id,
        workspace_id=workspace_id,
        name=local_name,
        defaults={"category": FALLBACK_CATEGORY, "order": next_order},
    )
    if created:
        logger.warning(
            "workflow_status_sync unmapped column title=%r team_id=%s workspace_id=%s "
            "-> team-local status id=%s category=%s",
            title,
            team_id,
            workspace_id,
            status.id,
            FALLBACK_CATEGORY,
        )
    return status.id


def _column_workflow_status_id(task) -> int | None:
    """The target mirror value for a task — free when the column is cached."""
    field = task._meta.get_field("column")
    cached = field.get_cached_value(task, default=None)
    if cached is not None and cached.pk == task.column_id:
        return cached.workflow_status_id

    from infrastructure.persistence.project.models import Column

    return Column.objects.filter(pk=task.column_id).values_list("workflow_status_id", flat=True).first()


def _sync_column_workflow_status(sender, instance, raw=False, **kwargs):
    if raw:
        return
    setattr(instance, _PRESYNC_ATTR, instance.workflow_status_id)
    if instance.workflow_status_id is not None:
        return  # already mapped — a title rename does NOT re-map in P1
    if instance.team_id is None or instance.workspace_id is None:
        return
    try:
        instance.workflow_status_id = resolve_workflow_status_id_for_column_title(
            team_id=instance.team_id,
            workspace_id=instance.workspace_id,
            title=instance.title,
        )
    except Exception:
        logger.exception(
            "workflow_status_sync column resolution failed title=%r team_id=%s workspace_id=%s",
            instance.title,
            instance.team_id,
            instance.workspace_id,
        )


def _sync_task_workflow_status(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw:
        return
    setattr(instance, _PRESYNC_ATTR, instance.workflow_status_id)
    if instance.column_id is None:
        instance.workflow_status_id = None
        return
    if (
        update_fields is not None
        and not (_TASK_COLUMN_FIELDS & set(update_fields))
        and instance.workflow_status_id is not None
    ):
        # This save does not touch the column and the mirror is present —
        # nothing to resolve, no extra query.
        return
    try:
        instance.workflow_status_id = _column_workflow_status_id(instance)
    except Exception:
        logger.exception(
            "workflow_status_sync task mirror resolution failed task_id=%s column_id=%s",
            instance.pk,
            instance.column_id,
        )


def _persist_mirror_after_partial_save(sender, instance, created=False, raw=False, update_fields=None, **kwargs):
    """Persist a mirror change a partial save dropped (one targeted UPDATE).

    ``update_fields`` is a frozenset a pre_save receiver cannot extend, so a
    save like the specialist move's writes the column but not the mirror the
    receiver set on the instance. Compare against the stashed pre-sync value
    and persist only when something actually changed.
    """
    if raw or not hasattr(instance, _PRESYNC_ATTR):
        return
    before = getattr(instance, _PRESYNC_ATTR)
    delattr(instance, _PRESYNC_ATTR)
    if created or update_fields is None:
        return  # the INSERT / full UPDATE already carried the mirror
    if _MIRROR_FIELDS & set(update_fields):
        return
    target = instance.workflow_status_id
    if before == target:
        return
    try:
        sender.objects.filter(pk=instance.pk).update(workflow_status_id=target)
    except Exception:
        logger.exception(
            "workflow_status_sync mirror persist failed model=%s pk=%s",
            sender.__name__,
            instance.pk,
        )


class DjangoWorkflowStatusSyncBridge:
    """Explicit signal registration (repo convention — never ``@receiver``)."""

    @staticmethod
    def register() -> None:
        from infrastructure.persistence.project.models import Column, Task

        pre_save.connect(
            _sync_column_workflow_status,
            sender=Column,
            weak=False,
            dispatch_uid="project:column_workflow_status_pre_save",
        )
        post_save.connect(
            _persist_mirror_after_partial_save,
            sender=Column,
            weak=False,
            dispatch_uid="project:column_workflow_status_post_save",
        )
        pre_save.connect(
            _sync_task_workflow_status,
            sender=Task,
            weak=False,
            dispatch_uid="project:task_workflow_status_pre_save",
        )
        post_save.connect(
            _persist_mirror_after_partial_save,
            sender=Task,
            weak=False,
            dispatch_uid="project:task_workflow_status_post_save",
        )
