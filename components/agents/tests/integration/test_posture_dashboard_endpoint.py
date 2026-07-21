"""Integration tests — the posture dashboard endpoint (HUD POSTURE module).

``GET /ai/agents/posture/dashboard/`` is a read-only, membership-checked
surface (``view_agents``, same mechanism as the kill-switch GET). Pins
the auth gates, the chart-ready response contract (series + KPI band
table + drill links), the persona lens differences, and the no-data
honesty on an empty workspace.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from infrastructure.persistence.ai.agents.models import AiActionDailyRollup
from infrastructure.persistence.workspaces.models import WorkspaceMembership

URL = "/ai/agents/posture/dashboard/"


@pytest.fixture
def roles(db):
    # ``membership_has_permission`` resolves the legacy ``role`` string
    # against the seeded system WorkspaceRole rows; migrations don't run
    # under pytest, so seed them explicitly.
    call_command("seed_workspace_roles")


def _member(workspace, user, role="member"):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role, status="active")


@pytest.mark.django_db
class TestPostureDashboardGating:
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

    def test_member_role_can_read(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        analyst = user_factory()
        _member(workspace, analyst, role="member")
        api_client.force_authenticate(analyst)

        response = api_client.get(URL, {"workspace_id": str(workspace.id)})

        assert response.status_code == 200, response.data

    def test_workspace_id_is_required(self, roles, api_client, user_factory):
        # A staff user bypasses the membership gate, so the view's own
        # missing-param branch is reachable.
        staff = user_factory()
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        api_client.force_authenticate(staff)
        response = api_client.get(URL)
        assert response.status_code == 400

    def test_unknown_persona_is_400(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        analyst = user_factory()
        _member(workspace, analyst, role="member")
        api_client.force_authenticate(analyst)

        response = api_client.get(URL, {"workspace_id": str(workspace.id), "persona": "board-member"})

        assert response.status_code == 400


@pytest.mark.django_db
class TestPostureDashboardContract:
    def _get(self, api_client, workspace, **params):
        api_client.force_authenticate(workspace.workspace_owner)
        return api_client.get(URL, {"workspace_id": str(workspace.id), **params})

    def test_empty_workspace_is_honest_about_no_data(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()

        response = self._get(api_client, workspace)

        assert response.status_code == 200, response.data
        data = response.data
        assert data["persona"] == "engineer"
        assert data["window_days"] == 7
        series = data["series"]
        assert set(series) == {
            "log_lines_per_day",
            "ai_cost_per_day",
            "findings_created_per_day",
            "runs_per_day",
        }
        for block in series.values():
            assert block["no_data"] is True
            assert len(block["points"]) == 7
            assert all(point["value"] == 0 for point in block["points"])
            assert block["link"]["panel"]
        assert series["ai_cost_per_day"]["projected_weekly_usd"] is None
        assert series["ai_cost_per_day"]["projected_monthly_usd"] is None
        assert data["kpi_bands"]["no_data"] is True
        assert data["kpi_bands"]["link"] == {"panel": "kanban"}

    def test_rollup_rows_feed_the_runs_and_cost_series(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()
        yesterday = (timezone.now() - timedelta(days=1)).date()
        AiActionDailyRollup.objects.create(
            workspace=workspace,
            date=yesterday,
            runs_total=4,
            runs_completed=3,
            runs_failed=1,
            tool_calls=9,
            tokens_input=1000,
            tokens_output=200,
            cost_usd="0.700000",
        )

        response = self._get(api_client, workspace)

        assert response.status_code == 200, response.data
        runs = response.data["series"]["runs_per_day"]
        cost = response.data["series"]["ai_cost_per_day"]
        assert runs["no_data"] is False
        runs_by_date = {p["date"]: p["value"] for p in runs["points"]}
        assert runs_by_date[yesterday.isoformat()] == 4
        assert cost["total_usd"] == pytest.approx(0.7)
        assert cost["projected_weekly_usd"] == pytest.approx(0.7)
        assert cost["projected_monthly_usd"] == pytest.approx(3.0)

    def test_persona_shapes_differ_but_share_facts(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()

        engineer = self._get(api_client, workspace, persona="engineer")
        executive = self._get(api_client, workspace, persona="executive")

        assert engineer.status_code == 200 and executive.status_code == 200
        assert "findings_posture" in engineer.data["posture"]
        assert "response_kpis" in engineer.data["posture"]
        assert "nacd_summary" in executive.data["posture"]
        assert "findings_posture" not in executive.data["posture"]
        # No composite score in either lens.
        import json

        blob = json.dumps(engineer.data, default=str) + json.dumps(executive.data, default=str)
        assert "posture_score" not in blob
        # Executive lens carries no per-row ids.
        assert "sample_task_ids" not in json.dumps(executive.data, default=str)
        assert "sample_run_ids" not in json.dumps(executive.data, default=str)

    def test_window_days_param_is_respected(self, roles, api_client, workspace_factory):
        workspace = workspace_factory()

        response = self._get(api_client, workspace, window_days="14")

        assert response.status_code == 200, response.data
        assert response.data["window_days"] == 14
        assert len(response.data["series"]["log_lines_per_day"]["points"]) == 14
