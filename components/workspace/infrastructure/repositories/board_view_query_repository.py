"""ORM adapter for the boards-as-views reads (ADR 0030 P2a).

Implements :class:`BoardViewQueryPort`. Deliberately built ON the column
board's lane machinery (``column_query_repository.board_ordered_tasks`` /
``check_team_membership`` / ``check_workspace_membership``) rather than a
parallel path — window size, eager-load set, task ordering and the
membership rules are byte-identical between the two board reads, so the P2
flag flip re-sources lanes without reordering a single card (dry-reuse.md).

Isolation posture (tenancy invariant 8): every queryset here is
workspace-scoped, and a view/team id belonging to ANOTHER workspace answers
exactly like a missing id — ``WorkspaceNotFoundError`` → 404 — never 403.
The column read predates this and still 403s cross-workspace column ids;
the new seam must not leak resource existence across the tenant boundary,
so it deliberately does not mirror that.

The view ``filter`` is the closed vocabulary on ``BoardView``
(``BOARD_VIEW_FILTER_KEYS``: project / source_type / min_severity /
assignee / tag). Filtering FAILS CLOSED: a malformed value, an unknown
severity, or a key whose data-side join does not exist yet matches
NOTHING — a broken filter on a security product must narrow visibility,
never widen it.
"""

from __future__ import annotations

import logging
import uuid as uuid_module
from typing import Any

from components.project.domain.workflow_status_vocabulary import CATEGORIES
from components.shared_kernel.domain.security import Severity
from components.workspace.application.ports.board_view_query_port import (
    BoardViewQueryPort,
    ViewBoard,
)
from components.workspace.application.ports.column_query_port import ColumnTasksPage
from components.workspace.domain.errors import WorkspaceNotFoundError
from components.workspace.infrastructure.repositories.column_query_repository import (
    board_ordered_tasks,
    check_team_membership,
)

logger = logging.getLogger(__name__)


def _severity_names_at_or_above(floor_name: str) -> list[str] | None:
    """Canonical severity names ranking >= ``floor_name`` (None = unknown floor)."""
    try:
        floor = Severity.from_name(str(floor_name))
    except ValueError:
        return None
    return [severity.value for severity in Severity if severity >= floor]


def apply_view_filter(tasks_queryset, view_filter: Any):
    """Restrict a task queryset to the view's closed-vocabulary ``filter``.

    One clause per key, ANDed. Semantics per key (ADR 0030 Decision §2 —
    closed keys, NOT a query language; extend deliberately, never ad hoc):

    - ``project``: ``task.project_id`` equals the value (the P1 backfill
      stores it as ``str(project.id)``; both str and int are accepted).
    - ``source_type``: exact match on ``task.source_type`` (the AI
      provenance label, e.g. ``ai.cloud_posture_drift``).
    - ``source_type_prefix``: ``task.source_type`` starts with the value
      (``"ai."`` = every AI-sourced card — the P3 Intake/Acting system
      views' source filter, mirroring the established
      ``task_source_type_prefix`` workflow-filter concept).
    - ``category``: the task's ``workflow_status.category`` equals the value
      (one of the domain vocabulary's CATEGORIES). The companion lane
      restriction lives in ``statuses_for_view`` — a category view renders
      only its own category's lanes.
    - ``min_severity``: severity floor over ``task.metadata.severity`` — the
      canonical top-level severity every finding card carries
      (``specialist_persistence_service``). A task with no severity is below
      every floor (a floor keeps noise off the board; unrated cards are
      exactly that noise).
    - ``assignee``: ``task.assigned_to`` contains the user id (UUID).
    - ``tag``: task-level tags do not EXIST yet — ADR 0015 tags tasks in its
      own later phase. Until that join lands this key matches nothing
      (fail closed + logged), rather than pretending an unfiltered board is
      the tag-filtered one.

    Any malformed value fails closed (``.none()``): system views are seeded
    well-formed, so a bad value means drift or tampering — never widen.
    """
    if not view_filter:
        return tasks_queryset
    if not isinstance(view_filter, dict):
        logger.warning("board_view filter malformed (non-dict) filter=%r", view_filter)
        return tasks_queryset.none()

    qs = tasks_queryset
    for key, value in view_filter.items():
        if key == "project":
            try:
                qs = qs.filter(project_id=int(str(value)))
            except (TypeError, ValueError):
                logger.warning("board_view filter bad project value=%r", value)
                return tasks_queryset.none()
        elif key == "source_type":
            if not isinstance(value, str) or not value:
                logger.warning("board_view filter bad source_type value=%r", value)
                return tasks_queryset.none()
            qs = qs.filter(source_type=value)
        elif key == "source_type_prefix":
            if not isinstance(value, str) or not value:
                logger.warning("board_view filter bad source_type_prefix value=%r", value)
                return tasks_queryset.none()
            qs = qs.filter(source_type__startswith=value)
        elif key == "category":
            if value not in CATEGORIES:
                logger.warning("board_view filter unknown category value=%r", value)
                return tasks_queryset.none()
            qs = qs.filter(workflow_status__category=value)
        elif key == "min_severity":
            allowed = _severity_names_at_or_above(value)
            if allowed is None:
                logger.warning("board_view filter unknown min_severity value=%r", value)
                return tasks_queryset.none()
            qs = qs.filter(metadata__severity__in=allowed)
        elif key == "assignee":
            try:
                assignee_id = uuid_module.UUID(str(value))
            except (TypeError, ValueError):
                logger.warning("board_view filter bad assignee value=%r", value)
                return tasks_queryset.none()
            qs = qs.filter(assigned_to__id=assignee_id)
        elif key == "tag":
            logger.info("board_view filter tag=%r matched fail-closed (task tagging lands with ADR 0015)", value)
            return tasks_queryset.none()
        else:
            # The model validates keys on save; an unknown key here means the
            # row bypassed validation — defence in depth, fail closed.
            logger.warning("board_view filter unknown key=%r", key)
            return tasks_queryset.none()
    return qs


class OrmBoardViewQueryRepository(BoardViewQueryPort):
    def fetch_team_views(self, *, team_id: Any, user: Any) -> list[Any]:
        team = self._get_team_for_member(team_id, user)
        check_team_membership(user, team)
        from django.db.models import Q

        from infrastructure.persistence.project.models import BoardView

        # Personal views (task #74) are visible to their CREATOR only; system
        # views to every team member. `-is_system` first guarantees the
        # contract "user views after system views" even though per-user order
        # sequences are gappy (each user only sees their own appends);
        # ("order", "id") is then the model's stated ordering.
        # No eager-load needed for the serializer's `created_by`/`mine`: both
        # read the local created_by_id (DRF PrimaryKeyRelatedField pk-only
        # optimization), so the list stays a single query.
        return list(
            BoardView.objects.filter(team=team, workspace=team.workspace)
            .filter(Q(is_system=True) | Q(created_by=user))
            .order_by("-is_system", "order", "id")
        )

    def fetch_view_board(self, *, view_id: Any, user: Any, tasks_limit: int) -> ViewBoard:
        view = self._get_view_for_member(view_id, user)
        check_team_membership(user, view.team)

        statuses = list(self._statuses_for(view))
        base = apply_view_filter(self._workspace_tasks_for(view), view.filter)
        for status_row in statuses:
            lane = board_ordered_tasks(base.filter(workflow_status=status_row))
            status_row.tasks_total = lane.count()
            status_row.windowed_tasks = list(lane[:tasks_limit])
        return ViewBoard(view=view, statuses=statuses)

    def fetch_view_lane_tasks(
        self, *, view_id: Any, status_id: Any, user: Any, offset: int, limit: int
    ) -> ColumnTasksPage:
        view = self._get_view_for_member(view_id, user)
        check_team_membership(user, view.team)

        status_row = self._statuses_for(view).filter(pk=status_id).first()
        if status_row is None:
            # Unknown id OR another team/workspace's status — same answer, no leak.
            raise WorkspaceNotFoundError("Status not found.")

        base = apply_view_filter(self._workspace_tasks_for(view), view.filter)
        lane = board_ordered_tasks(base.filter(workflow_status=status_row))
        total = lane.count()
        offset = max(0, int(offset))
        window = list(lane[offset : offset + limit])
        return ColumnTasksPage(tasks=window, total=total, offset=offset, limit=limit)

    # -- helpers --

    @staticmethod
    def _workspace_tasks_for(view):
        """The view's task universe — ALWAYS workspace- AND team-scoped.

        ``workflow_status`` is itself (team, workspace)-scoped, but the seam
        must not rely on a mirror column staying consistent for tenant
        isolation — scope explicitly (tenancy invariant: every queryset over
        workspace-scoped data filters on workspace_id).
        """
        from infrastructure.persistence.project.models import Task

        return Task.objects.filter(workspace=view.workspace, team=view.team)

    @staticmethod
    def _statuses_for(view):
        from infrastructure.persistence.project.models import WorkflowStatus

        # Meta.ordering is ("order", "id"); explicit for the same reason as views.
        statuses = WorkflowStatus.objects.filter(team=view.team, workspace=view.workspace).order_by("order", "id")
        # A category view renders ONLY its category's lanes (ADR 0030 §3: the
        # Intake/Acting system views are honest funnel surfaces, not six lanes
        # with four permanently empty). An unknown category fails closed to no
        # lanes, matching apply_view_filter's no-tasks answer for the same row.
        category = (view.filter or {}).get("category") if isinstance(view.filter, dict) else None
        if category is not None:
            statuses = statuses.filter(category=category) if category in CATEGORIES else statuses.none()
        return statuses

    @staticmethod
    def _get_team_for_member(team_id: Any, user: Any) -> Any:
        """Active team, visible only inside its own workspace (else 404)."""
        from components.workspace.application.facades.workspace_facade import user_is_workspace_member
        from infrastructure.persistence.team.models import Team

        team = Team.objects.select_related("workspace").filter(pk=team_id, status=Team.ACTIVE).first()
        if team is None or not user_is_workspace_member(user, team.workspace):
            raise WorkspaceNotFoundError("Team not found.")
        return team

    @staticmethod
    def _get_view_for_member(view_id: Any, user: Any) -> Any:
        """BoardView, visible only inside its own workspace (else 404).

        Personal views (task #74) narrow further: another member's personal
        view answers the SAME 404 as a missing id — the list never shows it,
        so no other read/write path may confirm it exists. Workspace
        admins/owners bypass (they can manage any personal view — the same
        admin bypass as ``check_team_membership``); the creator of an
        orphaned view (``created_by`` nulled by account deletion) no longer
        exists, so only admins reach those.
        """
        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_admin_or_owner,
            user_is_workspace_member,
        )
        from infrastructure.persistence.project.models import BoardView

        view = BoardView.objects.select_related("team", "team__workspace", "workspace").filter(pk=view_id).first()
        if view is None or not user_is_workspace_member(user, view.workspace):
            raise WorkspaceNotFoundError("View not found.")
        if not view.is_system:
            is_creator = view.created_by_id is not None and str(view.created_by_id) == str(user.id)
            if not is_creator and not user_is_workspace_admin_or_owner(user, view.workspace):
                raise WorkspaceNotFoundError("View not found.")
        return view
