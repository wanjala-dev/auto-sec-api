"""Repair the system ``BoardView`` rows missed between 0008 and the runtime seam.

Migration ``0008`` minted the derived system views (ADR 0030 §2) for every
team and project that existed when the P1 backfill ran. Nothing minted them
afterwards, so every team and project created since carried a full
``WorkflowStatus`` vocabulary (the P1 sync bridge seeds those lazily) and
ZERO views — which made ``feature.boards_as_views`` a strict LOSS of function
on those workspaces: the HUD renders the views bar only when the team has
views and hides the classic Board select while the flag is on, so the team
board and every project board were unreachable.

``django_system_board_view_bridge`` closes that from now on. This closes the
gap already in the data — it is the ONE pass the bridge cannot do, because a
row created in the gap is never saved again.

Shapes come from ``components/project/domain/system_board_views.py``, the
same module the bridge uses, so the repair and the runtime seam cannot drift
(pure domain — no Django, safe to import from a migration).

Two deliberate differences from 0008's §3:

* project views are created for every LIVE (``is_deleted=False``) project,
  not only ones that already have columns. Under ADR 0030 lanes come from
  the team's statuses, not the project's columns, so a column-less project
  renders perfectly well — and withholding its view is precisely what makes
  a freshly created project unreachable with the flag on.
* trashed projects are skipped, matching the bridge, which retires a view
  when its project is trashed.

Re-runnable by construction: every row lands via ``get_or_create`` keyed on
``uniq_board_view_slug_per_team``, and existing views are never renumbered.
Reverse is a no-op — these rows are derived, and dropping them would
re-create the very defect this repairs.
"""

import logging

from django.db import migrations
from django.db.models import Max

from components.project.domain.system_board_views import (
    TEAM_BOARD_VIEW_ORDER,
    project_board_view_spec,
    team_board_view_spec,
)

logger = logging.getLogger(__name__)


def backfill_missing_system_board_views(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Team = apps.get_model("team", "Team")
    Project = apps.get_model("project", "Project")
    BoardView = apps.get_model("project", "BoardView")

    seeded = 0
    for team in Team.objects.using(db_alias).all().iterator(chunk_size=500):
        workspace_id = team.workspace_id
        if workspace_id is None:
            continue

        team_spec = team_board_view_spec()
        _view, created = BoardView.objects.using(db_alias).get_or_create(
            team_id=team.id,
            workspace_id=workspace_id,
            slug=team_spec.slug,
            defaults={
                "name": team_spec.name,
                "filter": dict(team_spec.filter),
                "group_by": team_spec.group_by,
                "order": TEAM_BOARD_VIEW_ORDER,
                "is_system": True,
            },
        )
        seeded += int(created)

        next_order = (
            BoardView.objects.using(db_alias)
            .filter(team_id=team.id, workspace_id=workspace_id)
            .aggregate(max_order=Max("order"))["max_order"]
            or TEAM_BOARD_VIEW_ORDER
        ) + 1
        projects = Project.objects.using(db_alias).filter(team_id=team.id, is_deleted=False).order_by("id").iterator()
        for project in projects:
            spec = project_board_view_spec(project_id=project.id, title=project.title)
            _view, created = BoardView.objects.using(db_alias).get_or_create(
                team_id=team.id,
                workspace_id=workspace_id,
                slug=spec.slug,
                defaults={
                    "name": spec.name,
                    "filter": dict(spec.filter),
                    "group_by": spec.group_by,
                    "order": next_order,
                    "is_system": True,
                },
            )
            if created:
                next_order += 1
                seeded += 1

    if seeded:
        logger.info("system_board_view_backfill seeded=%s", seeded)


class Migration(migrations.Migration):
    dependencies = [
        ("project", "0010_boardview_created_by"),
        # The repair iterates Team rows from migration state.
        ("team", "0005_seed_red_blue_teams"),
    ]

    operations = [
        migrations.RunPython(backfill_missing_system_board_views, migrations.RunPython.noop),
    ]
