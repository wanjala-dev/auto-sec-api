"""Integration tests — the deep-run list endpoint (LIVE RUN dashboard card).

``GET /ai/agents/runs/?workspace_id=<id>&status=running`` lets a passive
dashboard card discover the run happening right now (or the most recent
one) without already holding a ``plan_id``. Pins the auth gates, the
newest-first ordering, the ``status`` filter, workspace isolation, and
the compact response contract each card row carries.
"""

from __future__ import annotations

import json
import uuid

import pytest
from django.core.management import call_command

from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog
from infrastructure.persistence.workspaces.models import WorkspaceMembership

URL = "/ai/agents/runs/"

# Fields that would leak run CONTENT (prompts / tool IO) — a redacted
# team projection must never carry any of these.
_SENSITIVE_KEYS = frozenset(
    {"goal", "payload", "tool_input", "tool_output", "system_prompt", "user_prompt", "llm_response"}
)


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


def _log(run, *, event_type="worker_started", agent_type="triage_agent", tool_name="", status="running"):
    return DeepRunLog.objects.create(
        deep_run=run,
        event_type=event_type,
        agent_type=agent_type,
        tool_name=tool_name,
        status=status,
        # A payload carrying tool IO — the redaction assertions prove it
        # never surfaces on the team projection.
        payload={"tool_input": "SECRET INPUT", "tool_output": "SECRET OUTPUT", "task_id": "x"},
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

    def test_row_carries_redacted_stage_projection(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)
        # A triage worker log → the projection should sit at the TRIAGE lane.
        _log(run, event_type="worker_started", agent_type="triage_agent")

        response = self._get(api_client, workspace)

        assert response.status_code == 200, response.data
        runs = response.data["runs"]
        assert len(runs) == 1
        row = runs[0]
        assert row["plan_id"] == run.plan_id
        assert row["status"] == "running"
        # 1 of 2 tasks done → 50%.
        assert row["task_count"] == 2
        assert row["completed_task_count"] == 1
        assert row["progress_percent"] == 50
        # Redacted 5-stage pipeline projection.
        assert row["current_stage"] == 1
        assert [s["key"] for s in row["stages"]] == ["alert", "triage", "finding", "draft_pr", "board"]
        assert [s["state"] for s in row["stages"]] == ["done", "active", "pending", "pending", "pending"]
        assert row["current_agent_type"] == "triage_agent"
        assert "current_agent_display_name" in row

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
class TestRunDetailIsOwnerOnly:
    """SECURITY CONTRACT: full run detail — prompts + tool inputs/outputs
    via ``retrieve`` and ``events`` — is OWNER-ONLY. A workspace teammate
    who did not start the run must never read its content; they get the
    redacted team projection on the list endpoint instead.
    """

    def test_teammate_cannot_retrieve_another_users_run(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        # Run started by the owner (stands in for the autonomous system user).
        run = _run(workspace, workspace.workspace_owner)
        _log(run, tool_name="triage_finding")
        # A different human, an active member of one of the workspace's teams.
        teammate = user_factory()
        team_factory(workspace=workspace, members=[teammate])
        api_client.force_authenticate(teammate)

        snap = api_client.get(f"{URL}{run.plan_id}/")
        events = api_client.get(f"{URL}{run.plan_id}/events/")

        # A teammate is NOT the owner → no access to prompts / tool IO.
        assert snap.status_code == 403, snap.data
        assert events.status_code == 403, events.data

    def test_owner_can_retrieve_own_run(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)
        api_client.force_authenticate(workspace.workspace_owner)

        snap = api_client.get(f"{URL}{run.plan_id}/")
        events = api_client.get(f"{URL}{run.plan_id}/events/")

        assert snap.status_code == 200, snap.data
        assert snap.data["plan_id"] == run.plan_id
        assert events.status_code == 200, events.data


@pytest.mark.django_db
class TestListProjectionCarriesNoRunContent:
    """SECURITY CONTRACT: the team-gated list projection must expose stage
    progress but NEVER prompt text or tool inputs/outputs, even when the
    underlying run logs carry them.
    """

    def test_no_sensitive_fields_on_any_row(self, roles, api_client, workspace_factory, user_factory, team_factory):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner, goal="SENSITIVE PROMPT TEXT")
        # Logs whose payloads carry tool IO the projection must not echo.
        _log(run, event_type="worker_started", agent_type="triage_agent")
        _log(run, event_type="tool_observation", tool_name="triage_finding")
        # Read as a NON-owner teammate — the projection's whole audience.
        teammate = user_factory()
        team_factory(workspace=workspace, members=[teammate])
        api_client.force_authenticate(teammate)

        response = api_client.get(URL, {"workspace_id": str(workspace.id)})

        assert response.status_code == 200, response.data
        rows = response.data["runs"]
        assert len(rows) == 1
        blob = json.dumps(rows)
        # No sensitive key names on any row, and no sensitive VALUES leak.
        for row in rows:
            assert _SENSITIVE_KEYS.isdisjoint(row.keys())
        assert "SENSITIVE PROMPT TEXT" not in blob
        assert "SECRET INPUT" not in blob
        assert "SECRET OUTPUT" not in blob
        # But the redacted progress IS present.
        assert rows[0]["current_stage"] == 2
        assert rows[0]["current_tool_name"] == "triage_finding"
