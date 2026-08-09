"""The operator's on-demand "DRAFT FIX PR" endpoint.

``POST /integrations/workspaces/<ws>/findings/<task_id>/draft-fix/``

Locks the three properties that make this button safe to put in front of an
operator: it NEVER runs the deep pipeline in-request, it is authorised no more
loosely than the sibling ``open-draft-pr`` endpoint it culminates in, and it always
answers with a reason instead of a dead click.
"""

from __future__ import annotations

from unittest import mock

import pytest

_TASK_PATH = "components.agents.infrastructure.tasks.agent_tasks.draft_fix_for_finding"


def _url(workspace_id, task_id):
    return f"/integrations/workspaces/{workspace_id}/findings/{task_id}/draft-fix/"


def _make_card(board, *, source_type="ai.code_security", agent_type="code_security_agent", payload=None):
    """A routable SAST finding card, shaped exactly as the board handler files it."""
    from infrastructure.persistence.project.models import Task

    workspace, team, column = board
    return Task.objects.create(
        workspace=workspace,
        team=team,
        column=column,
        title="High: sql-injection — app/views.py:42",
        source_type=source_type,
        created_by=workspace.workspace_owner,
        metadata={
            "agent_type": agent_type,
            "payload": {
                "rule_id": "python.django.security.injection.sql",
                "repo": "org/repo",
                "path": "app/views.py",
                "start_line": 42,
                "severity": "high",
                **(payload or {}),
            },
        },
    )


@pytest.fixture
def owner_ws(workspace_factory, team_factory):
    """A workspace with its agents board — the shape the board handler files cards onto."""
    from infrastructure.persistence.project.models import Column

    ws = workspace_factory()
    # The realistic state for a workspace that has AI triage: the product toggle on.
    # (``test_ai_disabled_workspace_is_refused`` turns it back off deliberately.)
    ws.ai_teammate_enabled = True
    ws.save(update_fields=["ai_teammate_enabled"])
    owner = ws.workspace_owner
    team = team_factory(workspace=ws, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=ws, project=None, title="Suggested", order=0, created_by=owner
    )
    return ws, owner, (ws, team, column)


@pytest.mark.django_db
class TestFindingDraftFixApi:
    def test_owner_gets_202_and_the_pipeline_never_runs_in_request(
        self, api_client, owner_ws, django_capture_on_commit_callbacks
    ):
        """202 + the finding's new state, enqueued — not a blocked request thread.

        The deep pipeline behind this is 10-30s of LLM calls; running it inline
        would block the worker, which is the standing problem this must not extend.
        The enqueue fires AFTER commit (celery-tasks §0) so the worker can never race
        the DRAFTING stamp the same request wrote — hence the capture fixture.
        """
        ws, owner, board = owner_ws
        card = _make_card(board)
        api_client.force_authenticate(owner)

        with mock.patch(_TASK_PATH) as task:
            with django_capture_on_commit_callbacks(execute=True):
                resp = api_client.post(_url(ws.id, card.id), {}, format="json")

        assert resp.status_code == 202, resp.data
        assert resp.data["data"]["state"] == "drafting"
        assert resp.data["data"]["already_in_flight"] is False
        task.delay.assert_called_once()
        assert task.delay.call_args.args[1] == str(card.id)

    def test_card_flips_to_drafting_immediately(self, api_client, owner_ws):
        """The click must be visible at once — the HUD shows DRAFTING while the
        specialist works, instead of an unexplained blank."""
        ws, owner, board = owner_ws
        card = _make_card(board)
        api_client.force_authenticate(owner)

        with mock.patch(_TASK_PATH):
            api_client.post(_url(ws.id, card.id), {}, format="json")

        card.refresh_from_db()
        assert card.metadata["triage_dispatch"]["state"] == "drafting"
        assert card.metadata["triage_dispatch"]["specialist"] == "code_security_agent"

    def test_viewer_is_denied(self, api_client, owner_ws, user_factory):
        """A read-only viewer must never reach a write into the customer's repo."""
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        ws, _, board = owner_ws
        card = _make_card(board)
        viewer = user_factory()
        WorkspaceMembership.objects.create(workspace=ws, user=viewer, role="viewer")
        api_client.force_authenticate(viewer)

        with mock.patch(_TASK_PATH) as task:
            resp = api_client.post(_url(ws.id, card.id), {}, format="json")

        assert resp.status_code == 403, resp.data
        task.delay.assert_not_called()

    def test_analyst_member_is_denied_no_second_door_to_a_repo_write(self, api_client, owner_ws, user_factory):
        """An analyst carries ``manage_findings`` but NOT ``manage_integrations``.

        The sibling ``open-draft-pr`` endpoint requires ``manage_integrations``, so
        gating this one on ``manage_findings`` alone would have opened a second,
        MORE permissive door onto the same repository write — a privilege
        escalation, not a convenience.
        """
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        ws, _, board = owner_ws
        card = _make_card(board)
        analyst = user_factory()
        WorkspaceMembership.objects.create(workspace=ws, user=analyst, role="member")
        api_client.force_authenticate(analyst)

        with mock.patch(_TASK_PATH) as task:
            resp = api_client.post(_url(ws.id, card.id), {}, format="json")

        assert resp.status_code == 403, resp.data
        task.delay.assert_not_called()

    def test_unauthenticated_is_denied(self, api_client, owner_ws):
        ws, _, board = owner_ws
        card = _make_card(board)
        resp = api_client.post(_url(ws.id, card.id), {}, format="json")
        assert resp.status_code in (401, 403)

    def test_unknown_finding_is_404_with_a_reason(self, api_client, owner_ws):
        ws, owner, board = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_url(ws.id, "999999"), {}, format="json")
        assert resp.status_code == 404, resp.data
        assert resp.data["reason"] == "finding_not_found"

    def test_operator_reading_finding_is_refused_with_a_reason(self, api_client, owner_ws):
        """Cloud-posture findings have no automated fix path — say so, don't hang."""
        ws, owner, board = owner_ws
        card = _make_card(board, source_type="ai.cloud_posture", agent_type="ai_teammate")
        api_client.force_authenticate(owner)

        with mock.patch(_TASK_PATH) as task:
            resp = api_client.post(_url(ws.id, card.id), {}, format="json")

        assert resp.status_code == 409, resp.data
        assert resp.data["reason"] == "not_routable"
        task.delay.assert_not_called()

    def test_existing_draft_pr_is_refused_not_duplicated(self, api_client, owner_ws):
        ws, owner, board = owner_ws
        card = _make_card(board, payload={"draft_pr": {"url": "https://github.com/org/repo/pull/7"}})
        api_client.force_authenticate(owner)

        with mock.patch(_TASK_PATH) as task:
            resp = api_client.post(_url(ws.id, card.id), {}, format="json")

        assert resp.status_code == 409, resp.data
        assert resp.data["reason"] == "draft_pr_exists"
        task.delay.assert_not_called()

    def test_double_click_enqueues_once(self, api_client, owner_ws, django_capture_on_commit_callbacks):
        """Idempotent under a double click — the second answers DRAFTING too."""
        ws, owner, board = owner_ws
        card = _make_card(board)
        api_client.force_authenticate(owner)

        with mock.patch(_TASK_PATH) as task:
            with django_capture_on_commit_callbacks(execute=True):
                first = api_client.post(_url(ws.id, card.id), {}, format="json")
                second = api_client.post(_url(ws.id, card.id), {}, format="json")

        assert first.status_code == 202
        assert second.status_code == 202
        assert second.data["data"]["already_in_flight"] is True
        assert task.delay.call_count == 1

    def test_ai_disabled_workspace_is_refused(self, api_client, owner_ws):
        ws, owner, board = owner_ws
        ws.ai_teammate_enabled = False
        ws.save(update_fields=["ai_teammate_enabled"])
        card = _make_card(board)
        api_client.force_authenticate(owner)

        with mock.patch(_TASK_PATH) as task:
            resp = api_client.post(_url(ws.id, card.id), {}, format="json")

        assert resp.status_code == 409, resp.data
        assert resp.data["reason"] == "ai_unavailable"
        task.delay.assert_not_called()
