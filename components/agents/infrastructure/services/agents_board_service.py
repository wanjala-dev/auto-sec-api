"""Seed + resolve the per-workspace Agents team Kanban board.

The "Agents" team is seeded by ``ensure_agents_team`` (see
``agent_permissions_service.py``). This service extends that by seeding a
default Project ("AI Findings") with four columns — Suggested / Under Review
/ Accepted / Dismissed — so posted findings have somewhere to land.

Idempotent. Safe to call on every finding; typical cost is one indexed read.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from infrastructure.persistence.project.models import Column, Project
    from infrastructure.persistence.team.models import Team

logger = logging.getLogger(__name__)

AI_FINDINGS_PROJECT_TITLE = "AI Findings"

SUGGESTED = "Suggested"
UNDER_REVIEW = "Under Review"
ACCEPTED = "Accepted"
DISMISSED = "Dismissed"

DEFAULT_COLUMNS: tuple[tuple[str, int, str], ...] = (
    (SUGGESTED, 0, "#FEF3C7"),      # amber-100
    (UNDER_REVIEW, 1, "#DBEAFE"),   # blue-100
    (ACCEPTED, 2, "#DCFCE7"),       # green-100
    (DISMISSED, 3, "#F3F4F6"),      # gray-100
)


@dataclass(frozen=True)
class AgentsBoard:
    team: Any
    project: Any
    columns_by_title: dict[str, Any]

    def column(self, title: str):
        """Return the column with *title*, case-insensitive.

        Raises KeyError if the column is missing — callers should rely on
        the constants (SUGGESTED, UNDER_REVIEW, ...) rather than raw strings.
        """
        for key, col in self.columns_by_title.items():
            if key.lower() == title.lower():
                return col
        raise KeyError(f"Agents board has no column titled '{title}'")


def ensure_agents_board(workspace) -> AgentsBoard:
    """Ensure the Agents team has an 'AI Findings' project with four columns.

    Returns an ``AgentsBoard`` bundling the team, project, and columns.
    """
    from infrastructure.persistence.project.models import Column, Project
    from infrastructure.persistence.team.models import Team

    from components.agents.infrastructure.services.agent_permissions_service import (
        ensure_ai_identity,
        ensure_agents_team,
    )

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
            workspace.id, team.id, project.id,
        )

    columns_by_title: dict[str, Column] = {}
    for title, order, color in DEFAULT_COLUMNS:
        column, created = Column.objects.get_or_create(
            project=project,
            team=team,
            workspace=workspace,
            title=title,
            defaults={
                "order": order,
                "color": color,
                "created_by": ai_user,
            },
        )
        if created:
            logger.info(
                "agents_board_column_seeded workspace_id=%s column_id=%s title=%s",
                workspace.id, column.id, title,
            )
        columns_by_title[title] = column

    return AgentsBoard(team=team, project=project, columns_by_title=columns_by_title)
