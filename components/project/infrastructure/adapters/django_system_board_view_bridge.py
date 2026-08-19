"""Runtime seam for the derived system ``BoardView`` rows (ADR 0030 §2).

Migration ``project.0008`` minted a system view for every team ("Board", the
unfiltered view) and every project board (``{"project": "<id>"}``) that
existed when the P1 backfill ran — and nothing minted them afterwards. The
status half of that backfill has had a runtime counterpart since P1
(``django_workflow_status_sync_bridge``); the view half never did. So every
team and project created since the backfill carried a full ``WorkflowStatus``
vocabulary and ZERO views, which made ``feature.boards_as_views`` a strict
LOSS of function on those workspaces: the views bar renders only when the
team has views, and the classic Board select is hidden while the flag is on,
so the team board and every project board became unreachable.

This bridge makes that invariant a runtime one, on the same ONE-seam
principle as its status sibling — every creator (the onboarding team seeder,
the ops backfill command, the agents board service, ``POST /project/``, the
tenant provisioner, every test factory) is covered without touching any of
them:

- ``Team`` post_save (create only): the team's unfiltered "Board" view.
- ``Project`` post_save (every save): the project's ``project-<pk>`` view,
  mirroring the project's live state — a trashed project (``is_deleted``)
  retires its view, a restore brings it back. Views are DERIVED, so a ghost
  view for a trashed board would be the same class of drift this fixes.

Both shapes come from ``components/project/domain/system_board_views.py``,
the ONE description shared with the ``0011`` repair migration that backfills
the teams and projects created in the gap.

Failure posture — deliberately NOT the status bridge's log-and-continue.
That bridge protects a *mirror* column while ``Column`` is still
authoritative for every read; here the row IS the feature, and a swallowed
failure would silently reproduce the exact defect this fixes. Both writes
are ``get_or_create`` on the row's unique constraint
(``uniq_board_view_slug_per_team``), so a concurrent creator loses the race
and re-reads rather than raising.

Registered from ``components/project/cli/apps.py`` ``ready()`` via explicit
``connect`` + ``dispatch_uid`` (repo convention: signal bridges, never
``@receiver``). Signals do not fire for historical models, so migrations are
unaffected.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save

from components.project.domain.system_board_views import (
    TEAM_BOARD_VIEW_ORDER,
    SystemBoardViewSpec,
    project_board_view_slug,
    project_board_view_spec,
    team_board_view_spec,
)

logger = logging.getLogger(__name__)


def _system_views(*, team_id, workspace_id):
    from infrastructure.persistence.project.models import BoardView

    return BoardView.objects.filter(team_id=team_id, workspace_id=workspace_id, is_system=True)


def _next_view_order(*, team_id, workspace_id) -> int:
    """Append after the team's current views — never renumber existing ones."""
    from django.db.models import Max

    from infrastructure.persistence.project.models import BoardView

    current = BoardView.objects.filter(team_id=team_id, workspace_id=workspace_id).aggregate(max_order=Max("order"))[
        "max_order"
    ]
    return (current if current is not None else TEAM_BOARD_VIEW_ORDER) + 1


def ensure_system_board_view(*, team_id, workspace_id, spec: SystemBoardViewSpec, order: int | None = None) -> None:
    """Idempotently persist one system view.

    The ``exists()`` short-circuit is not the ``exists()``-then-``filter()``
    anti-pattern (performance.md §3): it makes the steady state ONE query by
    skipping the order aggregate, which ``get_or_create``'s eagerly-evaluated
    ``defaults`` would otherwise force on every save. It also means an
    existing view is never renumbered.
    """
    from infrastructure.persistence.project.models import BoardView

    if BoardView.objects.filter(team_id=team_id, workspace_id=workspace_id, slug=spec.slug).exists():
        return

    view_order = order if order is not None else _next_view_order(team_id=team_id, workspace_id=workspace_id)
    _view, created = BoardView.objects.get_or_create(
        team_id=team_id,
        workspace_id=workspace_id,
        slug=spec.slug,
        defaults={
            "name": spec.name,
            "filter": dict(spec.filter),
            "group_by": spec.group_by,
            "order": view_order,
            "is_system": True,
        },
    )
    if created:
        logger.info(
            "system_board_view_seeded team_id=%s workspace_id=%s slug=%s",
            team_id,
            workspace_id,
            spec.slug,
        )


def _ensure_team_board_view(sender, instance, created=False, raw=False, **kwargs):
    if raw or not created or instance.workspace_id is None:
        return
    ensure_system_board_view(
        team_id=instance.pk,
        workspace_id=instance.workspace_id,
        spec=team_board_view_spec(),
        order=TEAM_BOARD_VIEW_ORDER,
    )


def _sync_project_board_view(sender, instance, raw=False, **kwargs):
    if raw or instance.team_id is None or instance.workspace_id is None:
        return
    if getattr(instance, "is_deleted", False):
        # Trashed: retire the derived view. Restoring the project re-creates
        # it (this same receiver, on the restoring save).
        removed, _ = (
            _system_views(team_id=instance.team_id, workspace_id=instance.workspace_id)
            .filter(slug=project_board_view_slug(instance.pk))
            .delete()
        )
        if removed:
            logger.info(
                "system_board_view_retired team_id=%s workspace_id=%s project_id=%s",
                instance.team_id,
                instance.workspace_id,
                instance.pk,
            )
        return
    ensure_system_board_view(
        team_id=instance.team_id,
        workspace_id=instance.workspace_id,
        spec=project_board_view_spec(project_id=instance.pk, title=instance.title),
    )


class DjangoSystemBoardViewBridge:
    """Explicit signal registration (repo convention — never ``@receiver``)."""

    @staticmethod
    def register() -> None:
        from infrastructure.persistence.project.models import Project
        from infrastructure.persistence.team.models import Team

        post_save.connect(
            _ensure_team_board_view,
            sender=Team,
            weak=False,
            dispatch_uid="project:team_system_board_view_post_save",
        )
        post_save.connect(
            _sync_project_board_view,
            sender=Project,
            weak=False,
            dispatch_uid="project:project_system_board_view_post_save",
        )
