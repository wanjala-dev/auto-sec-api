"""AI board cutover: one surface, canonical lanes (ADR 0030 P3, D2).

The AI finding's life used to cross TWO boards (QA 2026-08-16 F1): born in the
"AI Findings" project board's Suggested lane, specialist-moved to the Agents
*team* board's lazily-created Triage/Optimize lanes — with three project lanes
permanently dead and the ``project`` FK left stale on every moved card. This
migration collapses the AI surface onto ONE board — the **AI Findings project
board with the canonical six lanes** — per the ADR's P3 table:

    Suggested                  -> Todo
    Under Review / Triage / Optimize -> In Progress
    Accepted                   -> Complete
    Dismissed                  -> Canceled

(the same mapping ``workflow_status_vocabulary``'s alias table carries — the
table is resolved through that ONE module, never re-declared here).

Per Agents-team surface (``kind=ai_agents`` or any team owning an
"AI Findings" project):

- ensure the canonical six ``WorkflowStatus`` rows and the canonical six
  project-board columns (workflow_status stamped — historical models fire no
  signals, so the P1 bridge can't do it here);
- re-point EVERY task in a retired lane onto the canonical project-board lane,
  fixing ``team``/``project``/``column`` together (MoveTaskToBoardView
  semantics) and mirroring ``workflow_status``. The prior placement is
  recorded per card under the migration-owned ``metadata.board_cutover_p3``
  key, which is what makes the reverse exact;
- stamp the ``metadata.triage`` chip on AI-sourced cards from Triage
  (``triage_agent``) / Optimize (``optimization_agent``) — ONLY where no
  triage state exists yet (existing triage metadata is never clobbered), and
  the stamp is recorded so the reverse removes exactly what this added;
- soft-delete each retired lane once it is empty (``Column.is_deleted`` —
  every board read filters it out);
- seed the team's "Intake"/"Acting" system BoardViews (the ensure path covers
  future workspaces; this covers every existing one).

Re-runnable: every create is ``get_or_create``; the task pass only sees tasks
still sitting in retired lanes (none, after the first run).

Reverse: recorded cards go back to exactly their recorded lane (retired lanes
are un-soft-deleted / recreated as needed); cards born AFTER the cutover (no
record) are re-pointed by the inverse rule — Todo -> Suggested, In Progress ->
Triage/Optimize by ``metadata.triage.agent``, Complete -> Accepted, Canceled
-> Dismissed — reproducing the pre-P3 world (including its team-board lanes)
so the classic board reads exactly as before the cutover. The Intake/Acting
views are removed. The canonical project lanes are left in place (empty lanes
are harmless; deleting lanes mid-rollback is not).
"""

from django.db import migrations
from django.db.models import Q
from django.utils import timezone

from components.project.domain.workflow_status_vocabulary import (
    CANONICAL_STATUSES,
    resolve_status_name_for_column_title,
)

AI_FINDINGS_PROJECT_TITLE = "AI Findings"
CUTOVER_KEY = "board_cutover_p3"

# Retired lanes and where their chip attribution points (Triage/Optimize only).
_RETIRED_PROJECT_LANES = ("Suggested", "Under Review", "Accepted", "Dismissed")
_RETIRED_TEAM_LANES = ("Triage", "Optimize")
_CHIP_AGENT_BY_LANE = {"triage": "triage_agent", "optimize": "optimization_agent"}

# Column colors: canonical lanes reuse the agents-board seed palette
# (agents_board_service._COLUMN_COLORS); the reverse recreates the retired
# lanes with their historical colors.
_CANONICAL_COLORS = {
    "Backlog": "#F3F4F6",
    "Todo": "#FEF3C7",
    "In Progress": "#DBEAFE",
    "Testing": "#EDE9FE",
    "Complete": "#DCFCE7",
    "Canceled": "#F3F4F6",
}
_RETIRED_PROJECT_LANE_SEED = (
    ("Suggested", 0, "#FEF3C7"),
    ("Under Review", 1, "#DBEAFE"),
    ("Accepted", 2, "#DCFCE7"),
    ("Dismissed", 3, "#F3F4F6"),
)

_SYSTEM_VIEWS = (
    ("intake", "Intake", {"source_type_prefix": "ai.", "category": "unstarted"}),
    ("acting", "Acting", {"source_type_prefix": "ai.", "category": "started"}),
)


def _agents_teams(apps, db_alias):
    Team = apps.get_model("team", "Team")
    Project = apps.get_model("project", "Project")
    project_team_ids = (
        Project.objects.using(db_alias).filter(title=AI_FINDINGS_PROJECT_TITLE).values_list("team_id", flat=True)
    )
    return Team.objects.using(db_alias).filter(Q(kind="ai_agents") | Q(id__in=list(project_team_ids))).distinct()


def _ensure_statuses(WorkflowStatus, db_alias, team_id, workspace_id):
    status_by_name = {}
    for name, category, order in CANONICAL_STATUSES:
        status, _created = WorkflowStatus.objects.using(db_alias).get_or_create(
            team_id=team_id,
            workspace_id=workspace_id,
            name=name,
            defaults={"category": category, "order": order},
        )
        status_by_name[name] = status
    return status_by_name


def _ensure_canonical_project_columns(Column, db_alias, project, team_id, workspace_id, status_by_name):
    columns_by_name = {}
    for name, _category, order in CANONICAL_STATUSES:
        column, _created = Column.objects.using(db_alias).get_or_create(
            project_id=project.id,
            team_id=team_id,
            workspace_id=workspace_id,
            title=name,
            is_deleted=False,
            defaults={
                "order": order,
                "color": _CANONICAL_COLORS[name],
                "created_by_id": project.created_by_id,
                "workflow_status_id": status_by_name[name].id,
            },
        )
        if column.workflow_status_id is None:
            column.workflow_status_id = status_by_name[name].id
            column.save(update_fields=["workflow_status"])
        columns_by_name[name] = column
    return columns_by_name


def _ensure_system_views(BoardView, db_alias, team_id, workspace_id):
    from django.db.models import Max

    existing = set(
        BoardView.objects.using(db_alias)
        .filter(team_id=team_id, workspace_id=workspace_id, slug__in=[slug for slug, _n, _f in _SYSTEM_VIEWS])
        .values_list("slug", flat=True)
    )
    next_order = (
        BoardView.objects.using(db_alias)
        .filter(team_id=team_id, workspace_id=workspace_id)
        .aggregate(max_order=Max("order"))["max_order"]
        or 0
    ) + 1
    for slug, name, view_filter in _SYSTEM_VIEWS:
        if slug in existing:
            continue
        BoardView.objects.using(db_alias).get_or_create(
            team_id=team_id,
            workspace_id=workspace_id,
            slug=slug,
            defaults={
                "name": name,
                "filter": dict(view_filter),
                "group_by": "status",
                "order": next_order,
                "is_system": True,
            },
        )
        next_order += 1


def cutover_ai_board(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Project = apps.get_model("project", "Project")
    Column = apps.get_model("project", "Column")
    Task = apps.get_model("project", "Task")
    WorkflowStatus = apps.get_model("project", "WorkflowStatus")
    BoardView = apps.get_model("project", "BoardView")

    migrated_at = timezone.now().isoformat()

    for team in _agents_teams(apps, db_alias).iterator(chunk_size=200):
        workspace_id = team.workspace_id
        status_by_name = _ensure_statuses(WorkflowStatus, db_alias, team.id, workspace_id)

        project = (
            Project.objects.using(db_alias)
            .filter(workspace_id=workspace_id, team_id=team.id, title=AI_FINDINGS_PROJECT_TITLE)
            .order_by("created_at")
            .first()
        )

        # Retired lanes on this surface (live ones only).
        retired = list(
            Column.objects.using(db_alias)
            .filter(
                team_id=team.id,
                workspace_id=workspace_id,
                is_deleted=False,
            )
            .filter(
                Q(project__isnull=True, title__in=_RETIRED_TEAM_LANES)
                | Q(project__title=AI_FINDINGS_PROJECT_TITLE, title__in=_RETIRED_PROJECT_LANES)
            )
        )

        if project is None and retired:
            # Team-board Triage/Optimize exist but the project was never
            # seeded — create it so the cards have a canonical home.
            project = Project.objects.using(db_alias).create(
                workspace_id=workspace_id,
                team_id=team.id,
                title=AI_FINDINGS_PROJECT_TITLE,
                created_by_id=team.created_by_id,
            )

        if project is not None:
            canonical = _ensure_canonical_project_columns(
                Column, db_alias, project, team.id, workspace_id, status_by_name
            )

            for column in retired:
                target_name = resolve_status_name_for_column_title(column.title)
                if target_name is None:  # defensive — the retired set is all aliased
                    continue
                dest = canonical[target_name]
                chip_agent = _CHIP_AGENT_BY_LANE.get((column.title or "").strip().lower())

                tasks = Task.objects.using(db_alias).filter(column_id=column.id)
                for task in tasks.iterator(chunk_size=500):
                    meta = task.metadata or {}
                    record = meta.get(CUTOVER_KEY)
                    if not isinstance(record, dict):
                        record = {
                            "prior_column_id": task.column_id,
                            "prior_column_title": column.title,
                            # The COLUMN's own board (distinct from the task's
                            # prior project FK — the pre-P3 F1 shape kept a
                            # project-less Triage column under a task whose
                            # project stayed "AI Findings").
                            "prior_column_project_id": column.project_id,
                            "prior_project_id": task.project_id,
                            "prior_team_id": task.team_id,
                            "migrated_at": migrated_at,
                        }
                        meta[CUTOVER_KEY] = record

                    if (
                        chip_agent
                        and (task.source_type or "").startswith("ai.")
                        and not (meta.get("triage") or {}).get("status")
                    ):
                        # The chip shape mirrors what _finding_processing
                        # stamps (status/agent are the keys the HUD callout
                        # reads); ``suggested: False`` keeps the card
                        # re-attemptable by the specialist.
                        meta["triage"] = {
                            "status": "triaged",
                            "agent": chip_agent,
                            "triaged_at": migrated_at,
                            "actions": [f"re-pointed from the retired {column.title} lane (ADR 0030 P3)"],
                            "suggested": False,
                        }
                        record["stamped_triage"] = True

                    task.metadata = meta
                    task.column_id = dest.id
                    task.team_id = dest.team_id
                    task.project_id = dest.project_id
                    task.workflow_status_id = status_by_name[target_name].id
                    task.save(update_fields=["metadata", "column", "team", "project", "workflow_status", "updated_at"])

        # Retire lanes that are now empty (soft path — reads filter is_deleted).
        for column in retired:
            if not Task.objects.using(db_alias).filter(column_id=column.id).exists():
                column.is_deleted = True
                column.save(update_fields=["is_deleted"])

        _ensure_system_views(BoardView, db_alias, team.id, workspace_id)


def _revive_or_create_retired_lane(Column, db_alias, *, team_id, workspace_id, project, title):
    """Bring a retired lane back for the reverse re-point."""
    from django.db.models import Max

    if project is not None:
        query = Column.objects.using(db_alias).filter(
            team_id=team_id, workspace_id=workspace_id, project_id=project.id, title=title
        )
    else:
        query = Column.objects.using(db_alias).filter(
            team_id=team_id, workspace_id=workspace_id, project__isnull=True, title=title
        )
    column = query.order_by("id").first()
    if column is not None:
        if column.is_deleted:
            column.is_deleted = False
            column.save(update_fields=["is_deleted"])
        return column

    if project is not None:
        seed = {name: (order, color) for name, order, color in _RETIRED_PROJECT_LANE_SEED}
        order, color = seed.get(title, (0, "#FFFFFF"))
        created_by_id = project.created_by_id
        project_id = project.id
    else:
        max_order = (
            Column.objects.using(db_alias)
            .filter(team_id=team_id, workspace_id=workspace_id, project__isnull=True)
            .aggregate(max_order=Max("order"))["max_order"]
        )
        order, color = ((max_order or 0) + 1), "#FFFFFF"
        created_by_id = None
        project_id = None
    return Column.objects.using(db_alias).create(
        team_id=team_id,
        workspace_id=workspace_id,
        project_id=project_id,
        title=title,
        order=order,
        color=color,
        created_by_id=created_by_id,
    )


def _reverse_dest_for(Column, db_alias, *, task, canonical_lanes, team_id, workspace_id, project):
    """The inverse rule for an UNRECORDED (post-cutover-born) card.

    Todo -> Suggested; In Progress -> Triage/Optimize by the chip's acting
    agent (the team-board lanes, faithfully reproducing the pre-P3 world);
    Complete -> Accepted; Canceled -> Dismissed. Backlog/Testing (and any
    non-canonical lane) stay put — they had no pre-P3 equivalent.
    """
    title = next(
        (t for t, column in canonical_lanes.items() if column.id == task.column_id),
        None,
    )
    if title == "Todo":
        return _revive_or_create_retired_lane(
            Column, db_alias, team_id=team_id, workspace_id=workspace_id, project=project, title="Suggested"
        )
    if title == "In Progress":
        agent = ((task.metadata or {}).get("triage") or {}).get("agent") or ""
        lane = "Optimize" if agent == "optimization_agent" else "Triage"
        return _revive_or_create_retired_lane(
            Column, db_alias, team_id=team_id, workspace_id=workspace_id, project=None, title=lane
        )
    if title == "Complete":
        return _revive_or_create_retired_lane(
            Column, db_alias, team_id=team_id, workspace_id=workspace_id, project=project, title="Accepted"
        )
    if title == "Canceled":
        return _revive_or_create_retired_lane(
            Column, db_alias, team_id=team_id, workspace_id=workspace_id, project=project, title="Dismissed"
        )
    return None


def reverse_ai_board_cutover(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Project = apps.get_model("project", "Project")
    Column = apps.get_model("project", "Column")
    Task = apps.get_model("project", "Task")
    BoardView = apps.get_model("project", "BoardView")

    for team in _agents_teams(apps, db_alias).iterator(chunk_size=200):
        workspace_id = team.workspace_id
        project = (
            Project.objects.using(db_alias)
            .filter(workspace_id=workspace_id, team_id=team.id, title=AI_FINDINGS_PROJECT_TITLE)
            .order_by("created_at")
            .first()
        )

        # 1. Recorded cards: exact restore from the migration-owned key.
        recorded = Task.objects.using(db_alias).filter(
            workspace_id=workspace_id, team_id=team.id, metadata__has_key=CUTOVER_KEY
        )
        for task in recorded.iterator(chunk_size=500):
            meta = task.metadata or {}
            record = meta.pop(CUTOVER_KEY, None) or {}
            prior_column = (
                Column.objects.using(db_alias).filter(pk=record.get("prior_column_id")).first()
                if record.get("prior_column_id")
                else None
            )
            if prior_column is None and record.get("prior_column_title"):
                prior_column = _revive_or_create_retired_lane(
                    Column,
                    db_alias,
                    team_id=record.get("prior_team_id") or team.id,
                    workspace_id=workspace_id,
                    project=(project if record.get("prior_column_project_id") and project else None),
                    title=record["prior_column_title"],
                )
            elif prior_column is not None and prior_column.is_deleted:
                prior_column.is_deleted = False
                prior_column.save(update_fields=["is_deleted"])

            if record.get("stamped_triage"):
                meta.pop("triage", None)

            task.metadata = meta
            if prior_column is not None:
                task.column_id = prior_column.id
                task.workflow_status_id = prior_column.workflow_status_id
            task.team_id = record.get("prior_team_id") or task.team_id
            task.project_id = record.get("prior_project_id", task.project_id)
            task.save(update_fields=["metadata", "column", "team", "project", "workflow_status", "updated_at"])

        if project is None:
            BoardView.objects.using(db_alias).filter(
                team_id=team.id, workspace_id=workspace_id, slug__in=("intake", "acting"), is_system=True
            ).delete()
            continue

        # 2. Unrecorded cards born after the cutover: inverse rule.
        canonical_lanes = {
            column.title: column
            for column in Column.objects.using(db_alias).filter(
                team_id=team.id,
                workspace_id=workspace_id,
                project_id=project.id,
                title__in=[name for name, _c, _o in CANONICAL_STATUSES],
                is_deleted=False,
            )
        }

        unrecorded = Task.objects.using(db_alias).filter(
            workspace_id=workspace_id,
            team_id=team.id,
            source_type__startswith="ai.",
            column_id__in=[column.id for column in canonical_lanes.values()],
        )
        for task in unrecorded.iterator(chunk_size=500):
            dest = _reverse_dest_for(
                Column,
                db_alias,
                task=task,
                canonical_lanes=canonical_lanes,
                team_id=team.id,
                workspace_id=workspace_id,
                project=project,
            )
            if dest is None:
                continue
            task.column_id = dest.id
            # Pre-P3 world: team-board lanes kept the project FK as-is (the
            # F1 shape this reverse deliberately reproduces); project lanes
            # already match.
            task.workflow_status_id = dest.workflow_status_id
            task.save(update_fields=["column", "workflow_status", "updated_at"])

        BoardView.objects.using(db_alias).filter(
            team_id=team.id, workspace_id=workspace_id, slug__in=("intake", "acting"), is_system=True
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("project", "0008_backfill_workflow_statuses_and_board_views"),
        ("team", "0005_seed_red_blue_teams"),
    ]

    operations = [
        migrations.RunPython(cutover_ai_board, reverse_ai_board_cutover),
    ]
