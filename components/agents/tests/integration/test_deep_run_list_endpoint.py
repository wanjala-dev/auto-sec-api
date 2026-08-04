"""Integration tests — the deep-run list endpoint (LIVE RUN dashboard card).

``GET /ai/agents/runs/?workspace_id=<id>&status=running`` lets a passive
dashboard card discover the run happening right now (or the most recent
one) without already holding a ``plan_id``. Pins the auth gates, the
newest-first ordering, the ``status`` filter, workspace isolation, and
the compact response contract each card row carries.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.management import call_command

from infrastructure.persistence.ai.agents.models import DeepRun
from infrastructure.persistence.workspaces.models import WorkspaceMembership

URL = "/ai/agents/runs/"


@pytest.fixture
def roles(db):
    call_command("seed_workspace_roles")


def _member(workspace, user, role="member"):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role, status="active")


def _run(workspace, user, *, status=DeepRun.STATUS_RUNNING, goal="Triage pending findings", agent_type="triage_agent"):
    return DeepRun.objects.create(
        thread_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        user=user,
        workspace=workspace,
        status=status,
        state={
            "plan": {"goal": goal, "tasks": [{"title": "t1"}, {"title": "t2"}]},
            "completed_tasks": [{"title": "t1"}],
            "run_metadata": {"agent_type": agent_type, "goal": goal},
        },
    )


@pytest.mark.django_db
class TestDeepRunListGating:
    def test_anonymous_denied(self, api_client, workspace_factory):
        workspace = workspace_factory()
        response = api_client.get(URL, {"workspace_id": str(workspace.id)})
        assert response.status_code in (401, 403)

    def test_non_member_denied(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(outsider)

        response = api_client.get(URL, {"workspace_id": str(workspace.id)})

        assert response.status_code == 403

    def test_workspace_team_member_can_read(self, roles, api_client, workspace_factory, user_factory, team_factory):
        # Run observability is gated by ``_has_teammate_permissions`` (same
        # gate as ``/runs/stats/``): owner/staff or an active workspace-team
        # member. A team member is a teammate.
        workspace = workspace_factory()
        analyst = user_factory()
        team_factory(workspace=workspace, members=[analyst])
        api_client.force_authenticate(analyst)

        response = api_client.get(URL, {"workspace_id": str(workspace.id)})

        assert response.status_code == 200, response.data

    def test_bare_workspace_membership_without_team_is_denied(self, roles, api_client, workspace_factory, user_factory):
        # Documents the gate precisely: a WorkspaceMembership row alone is
        # NOT teammate access — the run stream is team-scoped.
        workspace = workspace_factory()
        analyst = user_factory()
        _member(workspace, analyst, role="member")
        api_client.force_authenticate(analyst)

        response = api_client.get(URL, {"workspace_id": str(workspace.id)})

        assert response.status_code == 403

    def test_workspace_id_is_required(self, roles, api_client, user_factory):
        user = user_factory()
        api_client.force_authenticate(user)
        response = api_client.get(URL)
        assert response.status_code == 400

    def test_unknown_workspace_is_404(self, roles, api_client, user_factory):
        staff = user_factory()
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        api_client.force_authenticate(staff)
        response = api_client.get(URL, {"workspace_id": str(uuid.uuid4())})
        assert response.status_code == 404


@pytest.mark.django_db
class TestDeepRunListContract:
    def _get(self, api_client, workspace, **params):
        api_client.force_authenticate(workspace.workspace_owner)
        return api_client.get(URL, {"workspace_id": str(workspace.id), **params})

    def test_empty_workspace_returns_empty_list(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()
        response = self._get(api_client, workspace)
        assert response.status_code == 200, response.data
        assert response.data == {"runs": []}

    def test_row_carries_plan_id_goal_progress_and_agent_label(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)

        response = self._get(api_client, workspace)

        assert response.status_code == 200, response.data
        runs = response.data["runs"]
        assert len(runs) == 1
        row = runs[0]
        assert row["plan_id"] == run.plan_id
        assert row["status"] == "running"
        assert row["goal"] == "Triage pending findings"
        # 1 of 2 tasks done → 50%.
        assert row["task_count"] == 2
        assert row["completed_task_count"] == 1
        assert row["progress_percent"] == 50
        # Alias-resolved label present so the card header needs no 2nd call.
        assert "agent_display_name" in row
        assert "agent_canonical_name" in row

    def test_status_filter_returns_only_running(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        _run(workspace, owner, status=DeepRun.STATUS_RUNNING)
        _run(workspace, owner, status=DeepRun.STATUS_COMPLETED)

        response = self._get(api_client, workspace, status="running")

        assert response.status_code == 200, response.data
        runs = response.data["runs"]
        assert len(runs) == 1
        assert runs[0]["status"] == "running"

    def test_newest_updated_first(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        older = _run(workspace, owner, goal="older")
        newer = _run(workspace, owner, goal="newer")
        # ``updated_at`` is auto_now; the second create is strictly newer.

        response = self._get(api_client, workspace)

        runs = response.data["runs"]
        assert [r["plan_id"] for r in runs][:2] == [newer.plan_id, older.plan_id]

    def test_isolated_to_workspace(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        other = workspace_factory()
        _run(other, other.workspace_owner)

        response = self._get(api_client, workspace)

        assert response.status_code == 200, response.data
        assert response.data == {"runs": []}


@pytest.mark.django_db
class TestDeepRunReadIsTeamGated:
    """Snapshot + events reads use the SAME workspace-teammate gate as the
    list/stats endpoints — so a teammate can drill into the workspace's
    autonomous runs (which run under a system/owner user), which is the
    whole point of the LIVE RUN card. Previously these were owner-only.
    """

    def test_teammate_can_retrieve_another_users_run(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        # Run started by the owner (stands in for the autonomous system user).
        run = _run(workspace, workspace.workspace_owner)
        # A different human, a member of one of the workspace's teams.
        teammate = user_factory()
        team_factory(workspace=workspace, members=[teammate])
        api_client.force_authenticate(teammate)

        snap = api_client.get(f"{URL}{run.plan_id}/")
        events = api_client.get(f"{URL}{run.plan_id}/events/")

        assert snap.status_code == 200, snap.data
        assert snap.data["plan_id"] == run.plan_id
        assert events.status_code == 200, events.data

    def test_non_member_cannot_retrieve_run(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)
        outsider = user_factory()
        api_client.force_authenticate(outsider)

        response = api_client.get(f"{URL}{run.plan_id}/")

        assert response.status_code == 403
