"""Backfill the status axis + system views from existing boards (ADR 0030 P1).

Per (team, workspace):

- create the six canonical ``WorkflowStatus`` rows (Backlog / Todo /
  In Progress / Testing / Complete / Canceled);
- map every existing ``Column`` (team-board AND project-board) onto a status
  by title through the ONE canonical vocabulary
  (``components/project/domain/workflow_status_vocabulary.py``): the six
  canonical titles map 1:1, user-legacy "Done" -> Complete, and the AI
  vocabularies map per the ADR's P3 table (Suggested -> Todo,
  Under Review / Triage / Optimize -> In Progress, Accepted -> Complete,
  Dismissed -> Canceled). Any OTHER title becomes a team-local status with
  category ``started`` and is LOGGED (the ADR's "exceptions logged");
- persist the decision on ``Column.workflow_status``;
- create the system ``BoardView`` rows: one unfiltered "Board" view per team,
  plus one ``{"project": "<id>"}`` view per project that has columns.

Then one global pass backfills ``Task.workflow_status`` from each task's
column (tasks with no column stay NULL).

Re-runnable by construction: every row lands via ``get_or_create`` keyed on
the model's unique constraint, and the task pass only touches rows still
NULL. Columns are never created, renamed, or deleted here — reads are
untouched in P1, Column stays authoritative.

Reverse is a no-op: rollback for P1 is reversing 0007, which drops the new
tables (and with them every row this migration wrote).
"""

import logging

from django.db import migrations
from django.db.models import OuterRef, Subquery

from components.project.domain.workflow_status_vocabulary import (
    CANONICAL_STATUSES,
    FALLBACK_CATEGORY,
    resolve_status_name_for_column_title,
)

logger = logging.getLogger(__name__)


def backfill_workflow_statuses_and_board_views(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Team = apps.get_model("team", "Team")
    Project = apps.get_model("project", "Project")
    Column = apps.get_model("project", "Column")
    Task = apps.get_model("project", "Task")
    WorkflowStatus = apps.get_model("project", "WorkflowStatus")
    BoardView = apps.get_model("project", "BoardView")

    for team in Team.objects.using(db_alias).all().iterator(chunk_size=500):
        workspace_id = team.workspace_id

        # ── 1. The canonical six, one vocabulary per team ────────────────
        status_by_name = {}
        for name, category, order in CANONICAL_STATUSES:
            status, _created = WorkflowStatus.objects.using(db_alias).get_or_create(
                team_id=team.id,
                workspace_id=workspace_id,
                name=name,
                defaults={"category": category, "order": order},
            )
            status_by_name[name] = status

        # ── 2. Map every column onto a status, persist on the column ────
        next_local_order = max((s.order for s in status_by_name.values()), default=0) + 1
        columns = Column.objects.using(db_alias).filter(team_id=team.id).order_by("order", "id")
        for column in columns:
            canonical_name = resolve_status_name_for_column_title(column.title)
            if canonical_name is not None:
                status = status_by_name[canonical_name]
            else:
                local_name = (column.title or "").strip() or column.title
                status, created = WorkflowStatus.objects.using(db_alias).get_or_create(
                    team_id=team.id,
                    workspace_id=workspace_id,
                    name=local_name,
                    defaults={"category": FALLBACK_CATEGORY, "order": next_local_order},
                )
                status_by_name[local_name] = status
                if created:
                    next_local_order += 1
                    # The ADR's "exceptions logged": an unmapped title means a
                    # team diverged from the canonical vocabulary — record it
                    # so P2/P3 reviews know which boards carry local lanes.
                    logger.warning(
                        "workflow_status_backfill unmapped column title=%r "
                        "column_id=%s team_id=%s workspace_id=%s -> team-local "
                        "status id=%s category=%s",
                        column.title,
                        column.id,
                        team.id,
                        workspace_id,
                        status.id,
                        FALLBACK_CATEGORY,
                    )
            if column.workflow_status_id != status.id:
                column.workflow_status_id = status.id
                column.save(update_fields=["workflow_status"])

        # ── 3. System views: the team board + each project board ────────
        BoardView.objects.using(db_alias).get_or_create(
            team_id=team.id,
            workspace_id=workspace_id,
            slug="board",
            defaults={
                "name": "Board",
                "filter": {},
                "group_by": "status",
                "order": 0,
                "is_system": True,
            },
        )
        projects_with_columns = (
            Project.objects.using(db_alias).filter(team_id=team.id, columns__isnull=False).distinct().order_by("id")
        )
        for view_order, project in enumerate(projects_with_columns, start=1):
            BoardView.objects.using(db_alias).get_or_create(
                team_id=team.id,
                workspace_id=workspace_id,
                slug=f"project-{project.id}",
                defaults={
                    "name": project.title,
                    "filter": {"project": str(project.id)},
                    "group_by": "status",
                    "order": view_order,
                    "is_system": True,
                },
            )

    # ── 4. Tasks mirror their column's status (one UPDATE, no iteration) ──
    column_status = Subquery(
        Column.objects.using(db_alias).filter(pk=OuterRef("column_id")).values("workflow_status_id")[:1]
    )
    Task.objects.using(db_alias).filter(column__isnull=False, workflow_status__isnull=True).update(
        workflow_status_id=column_status
    )


class Migration(migrations.Migration):
    dependencies = [
        ("project", "0007_workflowstatus_column_workflow_status_and_more"),
        # The backfill iterates Team rows from migration state.
        ("team", "0005_seed_red_blue_teams"),
    ]

    operations = [
        # Reverse is a no-op: P1 rollback reverses 0007, dropping the tables.
        migrations.RunPython(backfill_workflow_statuses_and_board_views, migrations.RunPython.noop),
    ]
