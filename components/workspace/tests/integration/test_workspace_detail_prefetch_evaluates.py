"""Regression net for the stripped-`sectors` prefetch drift.

The nonprofit fork removed the `sectors` app, but two repositories kept
prefetching `*__sectors`. Django only raises at queryset EVALUATION with
rows present, so the drift sat dormant until a real workspace with a real
team member hit `/api/v1/workspaces/<id>/` — a 500 on the tenant `wanjala`
(2026-08-18). These tests evaluate the actual read paths with rows, plus a
fitness check that no dead `__sectors` prefetch can come back anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestWorkspaceDetailEvaluates:
    def test_fetch_detail_evaluates_with_a_real_team_member(self, team_factory, user_factory):
        """The exact path that 500'd: teams with members, prefetched."""
        from components.workspace.infrastructure.repositories.workspace_detail_query_repository import (
            OrmWorkspaceDetailQueryRepository,
        )

        team = team_factory()
        member = user_factory()
        team.members.add(member)

        detail = OrmWorkspaceDetailQueryRepository().fetch_detail(workspace=team.workspace)
        assert len(detail.teams) == 1
        # Force the members prefetch to resolve (this is where the dead
        # `members__sectors` lookup used to raise AttributeError).
        assert [u.id for u in detail.teams[0].members.all()] == [member.id]


class TestNoDeadSectorsPrefetchRemains:
    def test_no_repository_prefetches_the_stripped_sectors_app(self):
        """Fitness function: the `sectors` app is gone — a `__sectors` or
        bare `"sectors"` prefetch string in any repository is dead code that
        500s at evaluation time. (Comments explaining the removal are fine.)
        """
        pattern = re.compile(r"[\"']([a-z_]+__)*sectors[\"']")
        offenders = []
        for path in (REPO_ROOT / "components").rglob("repositories/*.py"):
            for n, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(stripped):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{n}: {stripped}")
        assert offenders == [], "dead `sectors` prefetch(es) found:\n" + "\n".join(offenders)
