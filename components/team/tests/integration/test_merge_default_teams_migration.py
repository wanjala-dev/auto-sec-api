"""Integration test for the default-team dedupe migration logic.

Exercises ``merge_default_teams`` (team migration 0013) directly against real
models: a workspace with both a bootstrap "Contributors" team and a stray
"Default Team" (the dev/demo duplicate) must collapse to a single ``is_default``
"General" team, preserving memberships across the merge — including the
``UNIQUE(team, user)`` collision path.
"""

import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model

from infrastructure.persistence.team.models import Team, TeamMembership
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = pytest.mark.django_db

_migration = importlib.import_module("infrastructure.persistence.team.migrations.0013_merge_duplicate_default_teams")
merge_default_teams = _migration.merge_default_teams


def _make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", password="password123"
    )


def _seed_duplicate_default_teams():
    owner = _make_user("owner")
    member = _make_user("member")
    workspace = Workspace.objects.create(workspace_name="Dupe WS", workspace_owner=owner)
    # Drop any signal-created teams so the scenario is deterministic.
    Team.objects.filter(workspace=workspace).delete()

    canonical = Team.objects.create(workspace=workspace, title="Contributors", created_by=owner)
    dup = Team.objects.create(workspace=workspace, title="Default Team", created_by=owner)
    # owner is on BOTH -> exercises the UNIQUE(team, user) collision path.
    TeamMembership.objects.create(team=canonical, user=owner)
    TeamMembership.objects.create(team=dup, user=owner)
    # member is only on the duplicate -> must survive the re-point.
    TeamMembership.objects.create(team=dup, user=member)
    canonical.members.add(owner)
    dup.members.add(owner, member)
    return workspace, owner, member


def test_merge_collapses_to_single_general_default_team():
    workspace, owner, member = _seed_duplicate_default_teams()

    merge_default_teams(django_apps, None)

    teams = Team.objects.filter(workspace=workspace)
    assert teams.count() == 1
    survivor = teams.first()
    assert survivor.title == "General"  # "Contributors" -> "General"
    assert survivor.is_default is True

    # Memberships preserved without violating UNIQUE(team, user).
    member_user_ids = set(TeamMembership.objects.filter(team=survivor).values_list("user_id", flat=True))
    assert member_user_ids == {owner.id, member.id}
    assert set(survivor.members.values_list("id", flat=True)) == {
        owner.id,
        member.id,
    }


def test_merge_is_idempotent():
    workspace, owner, member = _seed_duplicate_default_teams()

    merge_default_teams(django_apps, None)
    merge_default_teams(django_apps, None)  # second run is a no-op

    teams = Team.objects.filter(workspace=workspace)
    assert teams.count() == 1
    assert teams.first().title == "General"
    assert teams.first().is_default is True
