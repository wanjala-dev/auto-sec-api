"""Seed + resolve the per-workspace Agents team Kanban board (ADR 0030 P3).

The "Agents" team is seeded by ``ensure_agents_team`` (see
``agent_permissions_service.py``). This service extends that by seeding the
default Project ("AI Findings") with the CANONICAL six lanes — the same
Backlog / Todo / In Progress / Testing / Complete / Canceled vocabulary every
other board uses (``workflow_status_vocabulary.CANONICAL_STATUSES``). The AI
surface no longer has its own column vocabulary (D2): a finding is born in
Todo, a specialist acting moves it to In Progress, human outcomes land in
Complete (accepted) or Canceled (dismissed) — AI state rides
``task.metadata.triage`` chips, not lanes. The retired Suggested /
Under Review / Accepted / Dismissed and the lazy team-board Triage / Optimize
lanes are re-pointed + soft-deleted by project migration
``0009_ai_board_cutover_to_canonical_lanes``.

Also seeds the Agents team's two SYSTEM board views (ADR 0030 Decision §3):
"Intake" (AI-sourced cards in ``unstarted`` statuses) and "Acting"
(``started``) — the two honest surfaces of what used to be two boards, over
ONE set of cards.

Idempotent. Safe to call on every finding; typical cost is two indexed reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from components.project.domain.workflow_status_vocabulary import (
    CANONICAL_STATUSES,
    CATEGORY_STARTED,
    CATEGORY_UNSTARTED,
)

if TYPE_CHECKING:
    from infrastructure.persistence.project.models import Column, Project
    from infrastructure.persistence.team.models import Team

logger = logging.getLogger(__name__)

AI_FINDINGS_PROJECT_TITLE = "AI Findings"

# Canonical lane titles (the ONE vocabulary — ADR 0030 Model A). Exposed as
# constants so callers address lanes without raw strings: intake targets TODO,
# specialist action targets IN_PROGRESS, human accept/dismiss land in
# COMPLETE / CANCELED (sign_off's reconciler imports the latter two through
# the ai_teammate facade).
BACKLOG = "Backlog"
TODO = "Todo"
IN_PROGRESS = "In Progress"
TESTING = "Testing"
COMPLETE = "Complete"
CANCELED = "Canceled"

# Lane colors keyed by canonical title. Todo keeps the retired Suggested
# lane's amber (intake reads the same at a glance); In Progress keeps
# Under Review's blue; Complete keeps Accepted's green.
_COLUMN_COLORS = {
    BACKLOG: "#F3F4F6",  # gray-100
    TODO: "#FEF3C7",  # amber-100
    IN_PROGRESS: "#DBEAFE",  # blue-100
    TESTING: "#EDE9FE",  # violet-100
    COMPLETE: "#DCFCE7",  # green-100
    CANCELED: "#F3F4F6",  # gray-100
}

#: (title, order, color) derived from CANONICAL_STATUSES so this board can
#: never drift from the status vocabulary (dry-reuse.md — one source).
DEFAULT_COLUMNS: tuple[tuple[str, int, str], ...] = tuple(
    (name, order, _COLUMN_COLORS[name]) for name, _category, order in CANONICAL_STATUSES
)

# The Agents team's system views (ADR 0030 Decision §3). Filters use the
# closed BoardView vocabulary (BOARD_VIEW_FILTER_KEYS): AI-sourced cards,
# split by status category — Intake shows what nothing has acted on yet,
# Acting shows what an agent is working / has worked.
INTAKE_VIEW_SLUG = "intake"
ACTING_VIEW_SLUG = "acting"
_SYSTEM_VIEWS: tuple[tuple[str, str, dict], ...] = (
    (INTAKE_VIEW_SLUG, "Intake", {"source_type_prefix": "ai.", "category": CATEGORY_UNSTARTED}),
    (ACTING_VIEW_SLUG, "Acting", {"source_type_prefix": "ai.", "category": CATEGORY_STARTED}),
)


@dataclass(frozen=True)
class AgentsBoard:
    team: Any
    project: Any
    columns_by_title: dict[str, Any]

    def column(self, title: str):
        """Return the column with *title*, case-insensitive.

        Raises KeyError if the column is missing — callers should rely on
        the constants (TODO, IN_PROGRESS, COMPLETE, CANCELED) rather than
        raw strings.
        """
        for key, col in self.columns_by_title.items():
            if key.lower() == title.lower():
                return col
        raise KeyError(f"Agents board has no column titled '{title}'")


def ensure_agents_board(workspace) -> AgentsBoard:
    """Ensure the Agents team's 'AI Findings' project has the canonical lanes.

    Also ensures the team's Intake / Acting system views exist (idempotent,
    covering workspaces created after the P3 data migration ran).
    Returns an ``AgentsBoard`` bundling the team, project, and columns.
    """
    from components.agents.infrastructure.services.agent_permissions_service import (
        ensure_agents_team,
        ensure_ai_identity,
    )
    from infrastructure.persistence.project.models import Column, Project

    _profile, ai_user = ensure_ai_identity(workspace)
    team: Team = ensure_agents_team(workspace, ai_user)

    project: Project = (
        Project.objects.filter(
            workspace=workspace,
            team=team,
            title=AI_FINDINGS_PROJECT_TITLE,
        )
        .order_by("created_at")
        .first()
    )
    if project is None:
        project = Project.objects.create(
            workspace=workspace,
            team=team,
            title=AI_FINDINGS_PROJECT_TITLE,
            created_by=ai_user,
        )
        logger.info(
            "agents_board_seeded workspace_id=%s team_id=%s project_id=%s",
            workspace.id,
            team.id,
            project.id,
        )

    columns_by_title: dict[str, Column] = {}
    for title, order, color in DEFAULT_COLUMNS:
        # ``is_deleted=False`` in the lookup so a lane retired by the P3
        # migration (or a future soft-delete) is never silently adopted as
        # the live one.
        column, created = Column.objects.get_or_create(
            project=project,
            team=team,
            workspace=workspace,
            title=title,
            is_deleted=False,
            defaults={
                "order": order,
                "color": color,
                "created_by": ai_user,
            },
        )
        if created:
            logger.info(
                "agents_board_column_seeded workspace_id=%s column_id=%s title=%s",
                workspace.id,
                column.id,
                title,
            )
        columns_by_title[title] = column

    _ensure_system_views(workspace, team)

    return AgentsBoard(team=team, project=project, columns_by_title=columns_by_title)


def _ensure_system_views(workspace, team) -> None:
    """Idempotently seed the Agents team's Intake / Acting BoardView rows.

    One read in the steady state; racing creators are serialized by the
    ``uniq_board_view_slug_per_team`` constraint (loser re-reads).
    """
    from django.db.models import Max

    from infrastructure.persistence.project.models import BoardView

    existing = set(
        BoardView.objects.filter(
            team=team,
            workspace=workspace,
            slug__in=[slug for slug, _name, _filter in _SYSTEM_VIEWS],
        ).values_list("slug", flat=True)
    )
    missing = [entry for entry in _SYSTEM_VIEWS if entry[0] not in existing]
    if not missing:
        return

    next_order = (
        BoardView.objects.filter(team=team, workspace=workspace).aggregate(max_order=Max("order"))["max_order"] or 0
    ) + 1
    for slug, name, view_filter in missing:
        _view, created = BoardView.objects.get_or_create(
            team=team,
            workspace=workspace,
            slug=slug,
            defaults={
                "name": name,
                "filter": dict(view_filter),
                "group_by": "status",
                "order": next_order,
                "is_system": True,
            },
        )
        if created:
            next_order += 1
            logger.info(
                "agents_board_view_seeded workspace_id=%s team_id=%s slug=%s",
                workspace.id,
                team.id,
                slug,
            )
