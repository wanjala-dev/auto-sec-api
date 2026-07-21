"""Integration tests — the open-draft-PR use case + HITL endpoint.

Real DB; the GitHub HTTP boundary is stubbed at ``requests.request`` inside
the adapter (per the HTTP-boundary stubbing rule — no real GitHub calls), and
the patch LLM is stubbed at ``LogPatchAdvisor.propose`` (matching how the
sibling advisor tests stub ``LogFixAdvisor.suggest``). Covers:

* happy path — branch/commit/PR calls issued, ``payload.draft_pr`` +
  provenance event + TaskComment written;
* every precondition failure (no connection, repo not allowlisted, finding
  needs_human, finding not triaged, capability off) with typed reasons;
* idempotency — a finding that already has ``payload.draft_pr`` returns the
  existing URL with ZERO GitHub API calls;
* the endpoint (workspace owner) — 201 with the PR URL.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.application.log_patch_advisor_service import PatchProposal
from components.integrations.application.providers.secret_envelope_provider import encrypt_secret
from components.integrations.application.use_cases.open_draft_pr_use_case import (
    DraftPrPreconditionError,
    OpenDraftPrUseCase,
)
from infrastructure.persistence.integrations.models import GitHubConnection
from infrastructure.persistence.project.models import Column, Task, TaskComment

_REPO = "wanjala-dev/auto-sec-api"
_OLD_FILE = "def handler():\n    return None\n"
_PATCH = PatchProposal(
    path="components/workflow/application/service.py",
    updated_content=_OLD_FILE + "\n\ndef run_due_schedules():\n    return None\n",
    change_summary="Add the missing run_due_schedules export.",
)


class _FakeGitHub:
    """Scripted ``requests.request`` replacement — records every call."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append((method, url))
        path = url.split("api.github.com")[-1]

        def _resp(payload, status=200):
            return SimpleNamespace(
                status_code=status,
                text=__import__("json").dumps(payload),
                json=lambda: payload,
            )

        if method == "GET" and path == f"/repos/{_REPO}":
            return _resp({"default_branch": "main"})
        if method == "GET" and path == f"/repos/{_REPO}/git/ref/heads/main":
            return _resp({"object": {"sha": "headsha123"}})
        if method == "GET" and path.startswith(f"/repos/{_REPO}/contents/"):
            return _resp({"content": base64.b64encode(_OLD_FILE.encode()).decode(), "sha": "filesha456"})
        if method == "POST" and path == f"/repos/{_REPO}/git/refs":
            return _resp({"ref": json["ref"]}, status=201)
        if method == "PUT" and path.startswith(f"/repos/{_REPO}/contents/"):
            return _resp({"commit": {"sha": "commitsha789"}}, status=201)
        if method == "POST" and path == f"/repos/{_REPO}/pulls":
            return _resp({"html_url": f"https://github.com/{_REPO}/pull/7", "number": 7}, status=201)
        return _resp({"message": f"unexpected {method} {path}"}, status=404)


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    intake = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
    )
    return workspace, owner, team, intake


def _triaged_finding(workspace, owner, team, column, *, needs_human=False, triaged=True, extra_payload=None):
    payload = {
        "service": "celery_worker",
        "level": "ERROR",
        "message": "ImportError: cannot import name 'run_due_schedules'",
        "signal": "ERROR in celery_worker",
        "severity": "high",
        "evidence": [
            {
                "type": "log_line",
                "detail": (
                    'File "/app/components/workflow/application/service.py", line 42, in run\n'
                    "ImportError: cannot import name 'run_due_schedules'"
                ),
            }
        ],
        "probable_cause": "Missing export.",
        "suggested_fix": "Add run_due_schedules to the module.",
        "needs_human": needs_human,
    }
    payload.update(extra_payload or {})
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="[HIGH] celery_worker · ImportError run_due_schedules",
        source_type="ai.log_watch",
        metadata={
            "agent_type": "triage_agent",
            "detector": "logwatch.error",
            "provenance": {
                "detector": "logwatch.error",
                "events": [{"actor": "detector:logwatch.error", "action": "filed finding", "at": "t0"}],
            },
            "triage": {"status": "triaged" if triaged else "pending", "needs_human": needs_human},
            "payload": payload,
        },
    )


def _connection(workspace, owner, *, allowlist=None, status=GitHubConnection.Status.CONNECTED):
    return GitHubConnection.objects.create(
        workspace=workspace,
        name="GitHub",
        repo_allowlist=allowlist if allowlist is not None else [_REPO],
        token_ciphertext=encrypt_secret("ghp_test_token"),
        status=status,
        created_by=owner,
    )


def _capability_agent(workspace, owner, *, enabled=True):
    from infrastructure.persistence.ai.agents.models import Agent

    return Agent.objects.create(
        agent_type="triage_agent",
        user=owner,
        workspace=workspace,
        config={"capabilities": {"open_draft_pr": enabled}},
    )


def _use_case():
    from components.integrations.application.providers.github_pr_provider import get_github_pr_adapter

    return OpenDraftPrUseCase(adapter_factory=get_github_pr_adapter)


_REQUESTS_PATH = "components.integrations.infrastructure.adapters.github_pr_adapter.requests.request"
_PROPOSE_PATH = "components.integrations.application.log_patch_advisor_service.LogPatchAdvisor.propose"


@pytest.mark.django_db
class TestOpenDraftPrHappyPath:
    def test_opens_pr_and_records_everything(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is True
        assert result.url == f"https://github.com/{_REPO}/pull/7"
        assert result.branch == f"autosec/finding-{task.id}"

        # The GitHub choreography actually happened, in order: repo → ref →
        # file → branch → commit → draft PR.
        methods = [(m, u.split("api.github.com")[-1]) for m, u in fake.calls]
        assert methods[0] == ("GET", f"/repos/{_REPO}")
        assert methods[1] == ("GET", f"/repos/{_REPO}/git/ref/heads/main")
        assert methods[2][0] == "GET" and "/contents/" in methods[2][1]
        assert methods[3] == ("POST", f"/repos/{_REPO}/git/refs")
        assert methods[4][0] == "PUT" and "/contents/" in methods[4][1]
        assert methods[5] == ("POST", f"/repos/{_REPO}/pulls")

        task.refresh_from_db()
        draft = task.metadata["payload"]["draft_pr"]
        assert draft["url"] == result.url
        assert draft["repo"] == _REPO
        assert draft["branch"] == result.branch
        assert draft["opened_by"] == str(owner.id)
        assert draft["opened_at"]

        events = task.metadata["provenance"]["events"]
        assert events[-1]["actor"] == f"agent:triage_agent via user:{owner.id}"
        assert result.url in events[-1]["action"]

        comment = TaskComment.objects.filter(task=task).first()
        assert comment is not None
        assert result.url in comment.comment

    def test_idempotent_when_pr_already_recorded(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        existing = {
            "url": f"https://github.com/{_REPO}/pull/3",
            "repo": _REPO,
            "branch": "autosec/finding-old",
            "opened_by": str(owner.id),
            "opened_at": "2026-07-18T00:00:00+00:00",
        }
        task = _triaged_finding(workspace, owner, team, column, extra_payload={"draft_pr": existing})
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is False
        assert result.url == existing["url"]
        assert fake.calls == []  # ZERO GitHub API calls
        assert TaskComment.objects.filter(task=task).count() == 0  # no duplicate side effects


@pytest.mark.django_db
class TestOpenDraftPrPreconditions:
    def _execute(self, workspace, task, owner):
        fake = _FakeGitHub()
        with mock.patch(_REQUESTS_PATH, new=fake):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

    def test_no_connection(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _capability_agent(workspace, owner)
        with pytest.raises(DraftPrPreconditionError) as exc:
            self._execute(workspace, task, owner)
        assert exc.value.reason == "no_github_connection"

    def test_disabled_connection(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner, status=GitHubConnection.Status.DISABLED)
        _capability_agent(workspace, owner)
        with pytest.raises(DraftPrPreconditionError) as exc:
            self._execute(workspace, task, owner)
        assert exc.value.reason == "connection_not_connected"

    def test_repo_not_allowlisted(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner, allowlist=["someone-else/other-repo"])
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()
        with mock.patch(_REQUESTS_PATH, new=fake), pytest.raises(DraftPrPreconditionError) as exc:
            _use_case().execute(
                workspace_id=str(workspace.id),
                task_id=str(task.id),
                performed_by=str(owner.id),
                repo=_REPO,
            )
        assert exc.value.reason == "repo_not_allowlisted"
        assert fake.calls == []

    def test_finding_needs_human_is_refused(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column, needs_human=True)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        with pytest.raises(DraftPrPreconditionError) as exc:
            self._execute(workspace, task, owner)
        assert exc.value.reason == "finding_needs_human"

    def test_untriaged_finding_is_refused(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column, triaged=False)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        with pytest.raises(DraftPrPreconditionError) as exc:
            self._execute(workspace, task, owner)
        assert exc.value.reason == "finding_not_triaged"

    def test_capability_off_is_refused(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner, enabled=False)
        with pytest.raises(DraftPrPreconditionError) as exc:
            self._execute(workspace, task, owner)
        assert exc.value.reason == "capability_disabled"

    def test_no_capability_agent_row_is_refused(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        with pytest.raises(DraftPrPreconditionError) as exc:
            self._execute(workspace, task, owner)
        assert exc.value.reason == "capability_disabled"

    def test_wrong_source_type_is_not_found(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        task.source_type = "ai.log_optimization"
        task.save(update_fields=["source_type"])
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        with pytest.raises(DraftPrPreconditionError) as exc:
            self._execute(workspace, task, owner)
        assert exc.value.reason == "finding_not_found"

    def test_ungrounded_patch_refused(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()
        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_PROPOSE_PATH, return_value=None),
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))
        assert exc.value.reason == "no_grounded_patch"
        # It read the repo/file but never wrote anything.
        assert all(m == "GET" for m, _ in fake.calls)


@pytest.mark.django_db
class TestOpenDraftPrEndpoint:
    def test_owner_opens_draft_pr(self, api_client, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()
        api_client.force_authenticate(owner)

        url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            response = api_client.post(url, {}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["success"] is True
        assert response.data["data"]["url"] == f"https://github.com/{_REPO}/pull/7"
        assert response.data["data"]["created"] is True

    def test_precondition_failure_maps_to_conflict(self, api_client, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        # No connection installed.
        api_client.force_authenticate(owner)
        url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 409
        assert response.data["reason"] == "no_github_connection"

    def test_unknown_finding_is_404(self, api_client, workspace_factory, team_factory):
        workspace, owner, _team, _column = _board(workspace_factory, team_factory)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        api_client.force_authenticate(owner)
        url = f"/integrations/workspaces/{workspace.id}/findings/00000000-0000-0000-0000-000000000000/open-draft-pr/"
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 404
        assert response.data["reason"] == "finding_not_found"

    def test_anonymous_is_denied(self, api_client, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        response = api_client.post(url, {}, format="json")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestAgentToolDelegation:
    def test_tool_returns_pr_url(self, workspace_factory, team_factory):
        from components.agents.infrastructure.adapters.langchain.tools import triage_agent as tools

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id))
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            result = tools.open_draft_pr(agent, json.dumps({"task_id": str(task.id)}))

        assert f"https://github.com/{_REPO}/pull/7" in result

    def test_tool_surfaces_typed_precondition(self, workspace_factory, team_factory):
        from components.agents.infrastructure.adapters.langchain.tools import triage_agent as tools

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column, needs_human=True)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        agent = SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id))

        result = tools.open_draft_pr(agent, str(task.id))
        assert "finding_needs_human" in result


@pytest.mark.django_db
class TestOpenDraftPrNotifiesOwner:
    def test_draft_pr_opened_notifies_workspace_owner(
        self, workspace_factory, team_factory, django_capture_on_commit_callbacks
    ):
        from infrastructure.persistence.notifications.models import Notification

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_PROPOSE_PATH, return_value=_PATCH),
            django_capture_on_commit_callbacks(execute=True),
        ):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        row = Notification.objects.filter(
            recipient=owner, metadata__kind="soc.draft_pr_opened"
        ).first()
        assert row is not None
        assert row.notification_type == Notification.NotificationType.AI_EVENT
        assert row.metadata["pr_url"] == result.url
        assert row.metadata["task_id"] == str(task.id)
        assert row.metadata["link"] == f"/ai/v2/{workspace.pk}"
        assert "draft PR" in row.verb

    def test_idempotent_replay_does_not_renotify(
        self, workspace_factory, team_factory, django_capture_on_commit_callbacks
    ):
        from infrastructure.persistence.notifications.models import Notification

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(
            workspace,
            owner,
            team,
            column,
            extra_payload={},
        )
        task.metadata["payload"]["draft_pr"] = {
            "url": f"https://github.com/{_REPO}/pull/7",
            "repo": _REPO,
            "branch": "autosec/finding-x",
        }
        task.save(update_fields=["metadata"])
        _connection(workspace, owner)

        with django_capture_on_commit_callbacks(execute=True):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is False
        assert Notification.objects.filter(metadata__kind="soc.draft_pr_opened").count() == 0
