"""N+1 regression guard for the workspace team list endpoint.

``GET /team/workspaces/<workspace_id>/teams/`` serves ``TeamSerializer`` for
every team in the workspace. That serializer reads ``created_by`` and ``plan``
(forward FKs via SlugRelatedField / ``get_plan_id``) and nests the full
``UserSerializer`` over ``members`` (M2M) — which itself touches each member's
``profile``, ``sectors`` and ``contributor_profile``. Before the fix,
``OrmMembershipQueryRepository.list_workspace_teams`` (components/membership —
the repository the team controller actually resolves through
``team_service.query_team_membership()``) returned a bare ``filter()``, so
every team fired its own FK + members queries and every member fired its own
profile/sectors/follower queries — a two-level N+1.

The repository now eager-loads what the serializer reads (select_related
``workspace``/``created_by``/``plan``, prefetch ``members`` with their
profile/followers/sectors/contributor-profile chains), and the identity
serializers memoise their per-user lookups (``get_workspaces`` /
``get_active_workspace``) per serializer context, so the query count must be
constant w.r.t. the number of teams on the page.

The member set is kept FIXED while the team count grows: per-DISTINCT-member
queries (one ``get_related_workspaces_queryset()`` per member) are memoised
per request, so with a fixed member set the count must not grow at all.
"""
from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

pytestmark = [pytest.mark.django_db]


def _list_query_count(api_client, workspace) -> int:
    with CaptureQueriesContext(connection) as ctx:
        res = api_client.get(f"/team/workspaces/{workspace.id}/teams/")
        assert res.status_code == 200, res.content
    return len(ctx.captured_queries)


def test_team_list_query_count_is_constant(
    api_client, workspace_factory, team_factory, user_factory
):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    api_client.force_authenticate(user=owner)

    # Fixed member set across all teams — growth in query count can then only
    # come from per-team lazy loads (created_by / plan / members M2M).
    members = [user_factory() for _ in range(2)]

    for _ in range(2):
        team_factory(workspace=workspace, members=members)
    # Warm up one-time caches (content types, etc.) so the baseline reflects
    # steady-state query count, not first-request setup.
    _list_query_count(api_client, workspace)
    baseline = _list_query_count(api_client, workspace)

    # More teams on the same page must NOT grow the query count; an N+1 adds
    # several queries (created_by, plan, members, per-member profile/sectors)
    # per new team.
    for _ in range(4):
        team_factory(workspace=workspace, members=members)
    grown = _list_query_count(api_client, workspace)

    assert grown == baseline, (
        f"Team-list N+1 regression: {baseline} queries with 2 teams but "
        f"{grown} with 6 — the count must be constant w.r.t. row count."
    )
