"""The historical "duplicate default teams" scenario, against CURRENT machinery.

FORK-DRIFT FIX (2026-08-16): this file used to import the wanjala-era team
migration ``0013_merge_duplicate_default_teams`` and call its merge function.
That migration does not exist in autosec — the fork reset every app to fresh
``0001`` migrations — so the module was un-collectable since the initial
commit and its ImportError interrupted the ENTIRE team test dir.

The defence against the historical "Contributors" + "Default Team" duplicate
now lives in ``ensure_workspace_scaffolding`` (workspace_utils): it prefers an
EXISTING default team regardless of title, falls back to a title match, and
only then creates one — so neither bootstrap nor downstream seeding ever mints
a second home team. These tests pin that guarantee for the legacy shapes the
old migration handled.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from components.workspace.infrastructure.adapters.workspace_utils import (
    ensure_workspace_scaffolding,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", password="password123"
    )


def _legacy_workspace():
    owner = _make_user("legacy-owner")
    workspace = Workspace.objects.create(workspace_name="Legacy WS", workspace_owner=owner)
    # Drop any signal-created teams so the scenario is deterministic.
    Team.objects.filter(workspace=workspace).delete()
    return workspace, owner


def test_existing_default_team_is_reused_regardless_of_title():
    """A legacy default team keeps its seat — scaffolding must not mint a second."""
    workspace, owner = _legacy_workspace()
    legacy = Team.objects.create(workspace=workspace, title="Contributors", created_by=owner, is_default=True)
    # The classic stray duplicate alongside it.
    Team.objects.create(workspace=workspace, title="Default Team", created_by=owner)

    team, _ = ensure_workspace_scaffolding(workspace, owner)

    assert team.id == legacy.id, "the existing default team is preferred regardless of its title"
    assert Team.objects.filter(workspace=workspace, is_default=True).count() == 1


def test_title_match_is_promoted_instead_of_creating_a_duplicate():
    """No is_default row yet: the team matching the requested title is promoted."""
    workspace, owner = _legacy_workspace()
    general = Team.objects.create(workspace=workspace, title="General", created_by=owner)

    team, _ = ensure_workspace_scaffolding(workspace, owner)

    assert team.id == general.id
    team.refresh_from_db()
    assert team.is_default is True
    # No second "General"/home team was created (Red Team is separate by kind).
    assert Team.objects.filter(workspace=workspace, is_default=True).count() == 1


def test_rescaffolding_never_creates_a_second_default_team():
    workspace, owner = _legacy_workspace()

    first, _ = ensure_workspace_scaffolding(workspace, owner)
    second, _ = ensure_workspace_scaffolding(workspace, owner)

    assert first.id == second.id
    assert Team.objects.filter(workspace=workspace, is_default=True).count() == 1
