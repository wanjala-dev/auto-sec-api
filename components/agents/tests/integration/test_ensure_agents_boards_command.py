"""Integration test for the ``ensure_agents_boards`` management command.

Phase 1 closeout of the Agents-as-Teammates migration. The 2026-04-17
production gap (two workspaces missed by the original
``0021_backfill_agents_board`` data migration) motivated this command.
These tests assert the command is the operator's primary self-healing
tool for that gap shape: idempotent, per-workspace failure isolated,
dry-run safe.

See ``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md`` Phase 1.
"""
from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _has_agents_team(workspace) -> bool:
    """Workspace has at least one active AI-agents team.

    Matches the command's filter: ``kind=AI_AGENTS`` is authoritative.
    The team's display title is rendered from the workspace's AI
    teammate name (e.g. "Nematron"), which varies per workspace and is
    renamed whenever the teammate's ``display_name`` changes.
    """
    from infrastructure.persistence.team.models import Team

    return Team.objects.filter(
        workspace=workspace,
        kind=Team.Kind.AI_AGENTS,
        status=Team.ACTIVE,
    ).exists()


def _agents_team_count(workspace) -> int:
    from infrastructure.persistence.team.models import Team

    return Team.objects.filter(
        workspace=workspace,
        kind=Team.Kind.AI_AGENTS,
        status=Team.ACTIVE,
    ).count()


class TestEnsureAgentsBoardsCommand:
    def test_backfills_workspace_without_agents_team(self, workspace_factory):
        from infrastructure.persistence.team.models import Team

        workspace = workspace_factory()
        # Delete any agents team the workspace_factory + bootstrap created
        # so we can verify the command's backfill path runs.
        Team.objects.filter(
            workspace=workspace, kind=Team.Kind.AI_AGENTS
        ).delete()
        assert not _has_agents_team(workspace)

        out = StringIO()
        call_command("ensure_agents_boards", stdout=out)

        assert _has_agents_team(workspace)
        assert "Backfill complete" in out.getvalue()
        assert "seeded=1" in out.getvalue()

    def test_idempotent_second_run_is_noop(self, workspace_factory):
        from infrastructure.persistence.team.models import Team

        workspace = workspace_factory()
        Team.objects.filter(
            workspace=workspace, kind=Team.Kind.AI_AGENTS
        ).delete()

        call_command("ensure_agents_boards", stdout=StringIO())
        assert _agents_team_count(workspace) == 1

        out = StringIO()
        call_command("ensure_agents_boards", stdout=out)

        # Second run should report "Nothing to do" since the first
        # backfill provisioned the team. No duplicate teams.
        assert "Nothing to do" in out.getvalue()
        assert _agents_team_count(workspace) == 1

    def test_dry_run_does_not_write(self, workspace_factory):
        from infrastructure.persistence.team.models import Team

        workspace = workspace_factory()
        Team.objects.filter(
            workspace=workspace, kind=Team.Kind.AI_AGENTS
        ).delete()
        assert not _has_agents_team(workspace)

        out = StringIO()
        call_command("ensure_agents_boards", "--dry-run", stdout=out)

        assert not _has_agents_team(workspace)
        assert "dry-run" in out.getvalue()
        assert "Need backfill: 1" in out.getvalue()

    def test_skips_workspaces_with_existing_agents_team(self, workspace_factory):
        from infrastructure.persistence.team.models import Team

        from components.agents.application.facades.ai_teammate_facade import (
            ensure_agents_board,
        )

        # Workspace with team already provisioned through the canonical path.
        provisioned = workspace_factory()
        Team.objects.filter(
            workspace=provisioned, kind=Team.Kind.AI_AGENTS
        ).delete()
        ensure_agents_board(provisioned)
        before_count = _agents_team_count(provisioned)
        assert before_count == 1

        # Workspace missing its team.
        missing = workspace_factory()
        Team.objects.filter(
            workspace=missing, kind=Team.Kind.AI_AGENTS
        ).delete()
        assert not _has_agents_team(missing)

        call_command("ensure_agents_boards", stdout=StringIO())

        # Provisioned workspace unchanged; missing one healed.
        assert _agents_team_count(provisioned) == before_count
        assert _has_agents_team(missing)
