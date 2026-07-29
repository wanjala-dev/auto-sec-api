"""Backfill existing workspaces for ADR 0007 (Red/Blue teams).

Schema-only migrations can't call app services, so this reproduces the seeding
minimally against the historical models:
  - each workspace's default (home) team → kind = blue_team (only if it's still a
    generic department/project_team kind, so a deliberately re-purposed home team
    is left alone);
  - each workspace gains a Red team (kind = red_team, is_default=False) if it has
    none, with the workspace owner enrolled as LEAD.

Findings/assets are untouched — they stay the workspace-scoped SSOT (ADR 0004).
Idempotent + reversible-as-noop.
"""

from django.db import migrations


def seed_red_blue(apps, schema_editor):
    Team = apps.get_model("team", "Team")
    TeamMembership = apps.get_model("team", "TeamMembership")
    Workspace = apps.get_model("workspaces", "Workspace")

    for workspace in Workspace.objects.all().iterator(chunk_size=500):
        # Promote the default/home team to Blue (defensive-by-default).
        default_team = Team.objects.filter(workspace=workspace, is_default=True).first()
        if default_team and default_team.kind in ("department", "project_team"):
            default_team.kind = "blue_team"
            default_team.save(update_fields=["kind"])

        # Seed the Red team if the workspace has none.
        if Team.objects.filter(workspace=workspace, kind="red_team").exists():
            continue
        owner = default_team.created_by if default_team else None
        if owner is None:
            # No home team to inherit an owner from — skip; bootstrap will seed it
            # on next workspace access.
            continue
        red = Team.objects.create(
            workspace=workspace,
            title="Red Team",
            created_by=owner,
            status="active",
            privacy="private",
            is_default=False,
            kind="red_team",
        )
        red.members.add(owner)
        TeamMembership.objects.get_or_create(team=red, user=owner, defaults={"role": "lead", "status": "active"})


def noop_reverse(apps, schema_editor):
    # Leaving the seeded Red teams + blue_team kind in place is harmless; nothing
    # to undo (a hard delete could orphan boards/tasks).
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0004_alter_team_kind"),
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_red_blue, noop_reverse),
    ]
