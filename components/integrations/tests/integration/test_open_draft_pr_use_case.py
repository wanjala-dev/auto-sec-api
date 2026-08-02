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
from infrastructure.persistence.integrations.models import VcsConnection
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


def _connection(
    workspace,
    owner,
    *,
    allowlist=None,
    status=VcsConnection.Status.CONNECTED,
    repo_root="",
    commit_identity=VcsConnection.CommitIdentity.PAT_OWNER,
    commit_author_name="",
    commit_author_email="",
):
    return VcsConnection.objects.create(
        workspace=workspace,
        provider=VcsConnection.Provider.GITHUB,
        name="GitHub",
        repo_allowlist=allowlist if allowlist is not None else [_REPO],
        repo_root=repo_root,
        commit_identity=commit_identity,
        commit_author_name=commit_author_name,
        commit_author_email=commit_author_email,
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
    from components.integrations.application.providers.vcs_provider import get_vcs_adapter

    return OpenDraftPrUseCase(adapter_factory=get_vcs_adapter)


_REQUESTS_PATH = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.requests.request"
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


class _BodyCapturingGitHub(_FakeGitHub):
    """Like ``_FakeGitHub`` but also records the PUT-contents commit body so a test
    can assert whether ``author``/``committer`` were sent."""

    def __init__(self):
        super().__init__()
        self.commit_body: dict | None = None

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = url.split("api.github.com")[-1]
        if method == "PUT" and "/contents/" in path:
            self.commit_body = json
        return super().__call__(method, url, headers=headers, json=json, params=params, timeout=timeout)


@pytest.mark.django_db
class TestOpenDraftPrCommitIdentity:
    """The commit's author/committer follows the connection's ``commit_identity``.

    Default (``pat_owner``) sends NO author (GitHub → PAT owner); ``operator`` stamps
    the approving user; ``custom`` stamps the stored name/email; an ``operator`` with
    no email falls back to no author rather than failing the PR."""

    def _run(self, workspace, owner, task):
        fake = _BodyCapturingGitHub()
        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))
        return fake

    def test_pat_owner_sends_no_author(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)  # default commit_identity = pat_owner
        _capability_agent(workspace, owner)

        fake = self._run(workspace, owner, task)
        assert fake.commit_body is not None
        assert "author" not in fake.commit_body
        assert "committer" not in fake.commit_body

    def test_custom_uses_stored_name_and_email(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(
            workspace,
            owner,
            commit_identity=VcsConnection.CommitIdentity.CUSTOM,
            commit_author_name="Auto-Sec Bot",
            commit_author_email="bot@autosec.example",
        )
        _capability_agent(workspace, owner)

        fake = self._run(workspace, owner, task)
        assert fake.commit_body["author"] == {"name": "Auto-Sec Bot", "email": "bot@autosec.example"}
        assert fake.commit_body["committer"] == {"name": "Auto-Sec Bot", "email": "bot@autosec.example"}

    def test_operator_uses_performed_by_identity(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner, commit_identity=VcsConnection.CommitIdentity.OPERATOR)
        _capability_agent(workspace, owner)

        fake = self._run(workspace, owner, task)
        author = fake.commit_body["author"]
        expected_name = owner.get_full_name() or owner.username or owner.email
        assert author["name"] == expected_name
        assert author["email"] == owner.email
        assert fake.commit_body["committer"] == author

    def test_operator_missing_email_falls_back_to_no_author(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner, commit_identity=VcsConnection.CommitIdentity.OPERATOR)
        _capability_agent(workspace, owner)

        # The approving user's email is blank → attribution falls back to the PAT
        # owner; the PR still opens (attribution never fails a PR).
        with mock.patch(
            "infrastructure.persistence.users.models.CustomUser.get_full_name", return_value="No Email User"
        ):
            owner.email = ""
            owner.save(update_fields=["email"])
            fake = self._run(workspace, owner, task)

        assert fake.commit_body is not None
        assert "author" not in fake.commit_body
        assert "committer" not in fake.commit_body


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
        _connection(workspace, owner, status=VcsConnection.Status.DISABLED)
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

    def test_candidate_file_not_in_repo_is_precondition(self, workspace_factory, team_factory):
        # The derived source file 404s AND auto-detect finds it nowhere in the repo tree
        # → a typed precondition (candidate_file_not_in_repo), NOT a propagated
        # VcsApiError. The advisor never runs.
        from components.integrations.application.ports.vcs_port import VcsApiError

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        _get_file_path = (
            "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.GitHubVcsAdapter.get_file"
        )
        fake = _FakeGitHub()
        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_get_file_path, side_effect=VcsApiError("not found", status_code=404)),
            mock.patch(f"{_ADAPTER}.list_tree", return_value=["README.md", "src/other.py"]),
            mock.patch(_PROPOSE_PATH) as propose,
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))
        assert exc.value.reason == "candidate_file_not_in_repo"
        propose.assert_not_called()

    def test_non_404_get_file_error_propagates(self, workspace_factory, team_factory):
        # A genuine API failure (e.g. 500) on get_file is NOT a precondition — it propagates.
        from components.integrations.application.ports.vcs_port import VcsApiError

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        _get_file_path = (
            "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.GitHubVcsAdapter.get_file"
        )
        fake = _FakeGitHub()
        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_get_file_path, side_effect=VcsApiError("server error", status_code=500)),
            pytest.raises(VcsApiError),
        ):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

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
class TestOpenDraftPrPatchValidation:
    """Verification-above-the-model: a destructive/broken patch opens NO PR.

    The advisor is stubbed to return a garbage patch (the #828 shape and
    variants). The use case must raise a typed precondition BEFORE any
    branch/commit/PR call — the fake GitHub records only the read calls.
    """

    def _run_with_patch(self, workspace, task, owner, updated_content, *, summary="bad patch"):
        fake = _FakeGitHub()
        bad = PatchProposal(path=_PATCH.path, updated_content=updated_content, change_summary=summary)
        # commit_file / open_draft_pr are spied so we can assert they never fire.
        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_PROPOSE_PATH, return_value=bad),
            mock.patch(f"{_ADAPTER}.commit_file") as commit,
            mock.patch(f"{_ADAPTER}.open_draft_pr") as open_pr,
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))
        return exc.value, fake, commit, open_pr

    def test_828_destructive_delete_opens_no_pr(self, workspace_factory, team_factory):
        # _OLD_FILE defines def handler(); the advisor "fixes" it by replacing the
        # whole file with a self-import that DELETES handler → removes_definitions.
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)

        gutted = "from components.workflow.application.service import handler\n"
        reason, fake, commit, open_pr = self._run_with_patch(workspace, task, owner, gutted)

        assert reason.reason == "patch_removes_definitions"
        # It read the repo/file but NEVER wrote — no branch, no commit, no PR.
        assert all(m == "GET" for m, _ in fake.calls)
        commit.assert_not_called()
        open_pr.assert_not_called()

    def test_syntax_broken_patch_opens_no_pr(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)

        broken = _OLD_FILE + "\n\ndef f(:\n    pass\n"
        reason, fake, commit, open_pr = self._run_with_patch(workspace, task, owner, broken)

        assert reason.reason == "patch_does_not_parse"
        commit.assert_not_called()
        open_pr.assert_not_called()

    def test_endpoint_maps_destructive_patch_to_4xx_not_502(self, api_client, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        api_client.force_authenticate(owner)

        gutted = "from components.workflow.application.service import handler\n"
        bad = PatchProposal(path=_PATCH.path, updated_content=gutted, change_summary="bad")
        fake = _FakeGitHub()
        url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=bad):
            response = api_client.post(url, {}, format="json")

        assert 400 <= response.status_code < 500, response.data
        assert response.status_code != 502
        assert response.data["reason"] == "patch_removes_definitions"
        # No draft PR was recorded on the finding.
        task.refresh_from_db()
        assert "draft_pr" not in (task.metadata.get("payload") or {})


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

    def test_candidate_file_missing_maps_to_4xx_not_502(self, api_client, workspace_factory, team_factory):
        # A finding whose derived file 404s in the repo must NOT surface as a generic 502
        # vcs_api_error — it's a 4xx precondition the operator can act on.
        from components.integrations.application.ports.vcs_port import VcsApiError

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()
        api_client.force_authenticate(owner)
        _get_file_path = (
            "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.GitHubVcsAdapter.get_file"
        )
        url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_get_file_path, side_effect=VcsApiError("not found", status_code=404)),
            mock.patch(f"{_ADAPTER}.list_tree", return_value=["README.md"]),
        ):
            response = api_client.post(url, {}, format="json")
        assert 400 <= response.status_code < 500, response.data
        assert response.status_code != 502
        assert response.data["reason"] == "candidate_file_not_in_repo"

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

        row = Notification.objects.filter(recipient=owner, metadata__kind="soc.draft_pr_opened").first()
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


# The runtime-relative path the finding derives (the deepest traceback frame).
_RUNTIME_PATH = "components/workflow/application/service.py"
_MONOREPO_PATH = f"api-v2.0/{_RUNTIME_PATH}"
_ADAPTER = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.GitHubVcsAdapter"


def _echo_path_patch(*, payload, path, current_content):
    """Advisor stub that echoes the path it is given — so the resolved (possibly
    monorepo-prefixed) path is what flows into commit_file, letting the test assert
    the branch/commit target the real repo path."""
    return PatchProposal(
        path=path,
        updated_content=_OLD_FILE + "\n\ndef run_due_schedules():\n    return None\n",
        change_summary="Add the missing run_due_schedules export.",
    )


@pytest.mark.django_db
class TestOpenDraftPrMonorepoResolution:
    """The finding derives a runtime path that lives under a monorepo subdirectory."""

    def test_auto_detect_resolves_and_commits_prefixed_path(self, workspace_factory, team_factory):
        from components.integrations.application.ports.vcs_port import RepoFile, VcsApiError

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)  # no repo_root → auto-detect
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        committed: dict = {}

        def _get_file(self, repo, path, ref):
            # The runtime path 404s at the root; the resolved (prefixed) path 200s.
            if path == _RUNTIME_PATH:
                raise VcsApiError("not found", status_code=404)
            if path == _MONOREPO_PATH:
                return RepoFile(path=path, content=_OLD_FILE, sha="filesha456")
            raise VcsApiError("not found", status_code=404)

        def _commit_file(self, repo, branch, path, new_content, message, file_sha, author=None):
            from components.integrations.application.ports.vcs_port import CommittedFile

            committed["path"] = path
            return CommittedFile(path=path, commit_sha="commitsha789")

        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(f"{_ADAPTER}.get_file", new=_get_file),
            mock.patch(f"{_ADAPTER}.list_tree", return_value=["README.md", _MONOREPO_PATH]),
            mock.patch(f"{_ADAPTER}.commit_file", new=_commit_file),
            mock.patch(_PROPOSE_PATH, side_effect=_echo_path_patch),
        ):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is True
        # The commit — hence the whole PR — targets the resolved monorepo path.
        assert committed["path"] == _MONOREPO_PATH

    def test_explicit_repo_root_prefixes_without_tree_fetch(self, workspace_factory, team_factory):
        from components.integrations.application.ports.vcs_port import RepoFile

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner, repo_root="api-v2.0")
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        committed: dict = {}

        def _get_file(self, repo, path, ref):
            return RepoFile(path=path, content=_OLD_FILE, sha="filesha456")

        def _commit_file(self, repo, branch, path, new_content, message, file_sha, author=None):
            from components.integrations.application.ports.vcs_port import CommittedFile

            committed["path"] = path
            return CommittedFile(path=path, commit_sha="commitsha789")

        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(f"{_ADAPTER}.get_file", new=_get_file),
            mock.patch(f"{_ADAPTER}.list_tree") as list_tree,
            mock.patch(f"{_ADAPTER}.commit_file", new=_commit_file),
            mock.patch(_PROPOSE_PATH, side_effect=_echo_path_patch),
        ):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is True
        assert committed["path"] == _MONOREPO_PATH
        list_tree.assert_not_called()  # explicit override skips auto-detect entirely

    def test_ambiguous_match_is_precondition(self, workspace_factory, team_factory):
        from components.integrations.application.ports.vcs_port import VcsApiError

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        def _get_file(self, repo, path, ref):
            raise VcsApiError("not found", status_code=404)

        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(f"{_ADAPTER}.get_file", new=_get_file),
            mock.patch(
                f"{_ADAPTER}.list_tree",
                return_value=[f"backend/{_RUNTIME_PATH}", f"legacy/{_RUNTIME_PATH}"],
            ),
            mock.patch(_PROPOSE_PATH) as propose,
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))
        assert exc.value.reason == "ambiguous_candidate_path"
        propose.assert_not_called()

    def test_no_tree_match_is_candidate_file_not_in_repo(self, workspace_factory, team_factory):
        from components.integrations.application.ports.vcs_port import VcsApiError

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        def _get_file(self, repo, path, ref):
            raise VcsApiError("not found", status_code=404)

        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(f"{_ADAPTER}.get_file", new=_get_file),
            mock.patch(f"{_ADAPTER}.list_tree", return_value=["README.md", "src/other.py"]),
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))
        assert exc.value.reason == "candidate_file_not_in_repo"


@pytest.mark.django_db
class TestOpenDraftPrAmbiguousEndpoint:
    def test_ambiguous_maps_to_4xx_not_502(self, api_client, workspace_factory, team_factory):
        from components.integrations.application.ports.vcs_port import VcsApiError

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()
        api_client.force_authenticate(owner)

        def _get_file(self, repo, path, ref):
            raise VcsApiError("not found", status_code=404)

        url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(f"{_ADAPTER}.get_file", new=_get_file),
            mock.patch(
                f"{_ADAPTER}.list_tree",
                return_value=[f"backend/{_RUNTIME_PATH}", f"legacy/{_RUNTIME_PATH}"],
            ),
        ):
            response = api_client.post(url, {}, format="json")
        assert 400 <= response.status_code < 500, response.data
        assert response.status_code != 502
        assert response.data["reason"] == "ambiguous_candidate_path"
