"""Backbone VCS chain — connect → verify → preview → open draft PR, in ONE walk.

The sibling suites pin each leg in isolation (``test_vcs_connection_api`` the
CRUD/verify, ``test_preview_draft_pr_use_case`` / ``test_open_draft_pr_use_case``
the use cases + endpoints); this suite chains them through the REAL endpoints the
way an operator lives it, sharing ONE scripted GitHub (``_FakeGitHub`` — the
requests-level stub, so verify/preview/open all exercise the real adapter):

    POST …/vcs-connections/                         token stored encrypted, connected
    POST …/vcs-connections/<id>/verify/             GitHub probe → verified stamp
    POST …/findings/<task>/preview-draft-pr/        grounded diff + provenance on the card
    POST …/findings/<task>/open-draft-pr/           draft PR + payload.draft_pr +
                                                    provenance event + card comment
    POST open again                                 idempotent 200, no second PR

DRY: the GitHub script + board/finding/capability builders are imported from the
open-draft-pr suite rather than re-rolled.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.tests.integration.test_open_draft_pr_use_case import (
    _PATCH,
    _PROPOSE_PATH,
    _REPO,
    _REQUESTS_PATH,
    _board,
    _capability_agent,
    _FakeGitHub,
    _triaged_finding,
)
from infrastructure.persistence.integrations.models import VcsConnection
from infrastructure.persistence.project.models import Task, TaskComment

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class _FakeGitHubWithUser(_FakeGitHub):
    """The chain also exercises verify's token probe (``GET /user``), which the
    open-draft-pr script doesn't need — add just that route."""

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        if method == "GET" and url.split("api.github.com")[-1] == "/user":
            self.calls.append((method, url))
            from types import SimpleNamespace

            return SimpleNamespace(
                status_code=200, text='{"login": "autosec-bot"}', json=lambda: {"login": "autosec-bot"}
            )
        return super().__call__(method, url, headers=headers, json=json, params=params, timeout=timeout)


def _base(ws_id) -> str:
    return f"/integrations/workspaces/{ws_id}/vcs-connections/"


class TestBackboneVcsDraftPrChain:
    def test_connect_verify_preview_open_in_sequence(self, api_client, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _capability_agent(workspace, owner)
        api_client.force_authenticate(owner)
        fake = _FakeGitHubWithUser()

        # 1. Connect — the token is stored encrypted and never echoed.
        created = api_client.post(
            _base(workspace.id),
            {"provider": "github", "name": "GitHub", "repo_allowlist": [_REPO], "token": "ghp_test_token"},
            format="json",
        )
        assert created.status_code == 201, created.data
        connection = created.data["data"]
        assert connection["has_token"] is True and "token" not in connection
        assert "ghp_test_token" not in created.content.decode()

        # 2. Verify — the REAL GitHub adapter probes the allowlisted repo
        #    against the scripted GitHub; the row gets its verified stamp.
        with mock.patch(_REQUESTS_PATH, new=fake):
            verified = api_client.post(f"{_base(workspace.id)}{connection['id']}/verify/", format="json")
        assert verified.status_code == 200, verified.data
        assert verified.data["data"]["status"] == "connected"
        assert verified.data["data"]["last_verified_at"] is not None
        assert ("GET", f"https://api.github.com/repos/{_REPO}") in fake.calls

        # 3. Preview — grounded diff returned, preview stamped on the card as
        #    provenance, NO pull request opened yet.
        preview_url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/preview-draft-pr/"
        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            previewed = api_client.post(preview_url, {}, format="json")
        assert previewed.status_code == 200, previewed.data
        preview = previewed.data["data"]
        assert preview["repo"] == _REPO
        assert preview["path"] == _PATCH.path
        assert "run_due_schedules" in preview["diff"]
        assert not any(m == "POST" and u.endswith("/pulls") for m, u in fake.calls), "preview must never open a PR"
        task.refresh_from_db()
        assert task.metadata["payload"]["proposed_patch"]["path"] == _PATCH.path
        assert TaskComment.objects.filter(task=task, comment__icontains="Proposed-fix preview").exists()

        # 4. Open — the draft PR lands; every provenance side effect with it.
        open_url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            opened = api_client.post(open_url, {}, format="json")
        assert opened.status_code == 201, opened.data
        pr = opened.data["data"]
        assert pr["url"] == f"https://github.com/{_REPO}/pull/7"
        assert pr["branch"] == f"autosec/finding-{task.id}"

        # The GitHub choreography actually ran, ending in the draft PR create.
        methods = [(m, u.split("api.github.com")[-1]) for m, u in fake.calls]
        assert methods[-1] == ("POST", f"/repos/{_REPO}/pulls")
        assert ("POST", f"/repos/{_REPO}/git/refs") in methods

        # Provenance on the card (the HARD rule: every AI action lands on the board):
        task.refresh_from_db()
        draft = task.metadata["payload"]["draft_pr"]
        assert draft["url"] == pr["url"]
        assert draft["opened_by"] == str(owner.id)
        events = task.metadata["provenance"]["events"]
        assert pr["url"] in events[-1]["action"]
        assert TaskComment.objects.filter(task=task, comment__icontains=pr["url"]).exists()

        # 5. Idempotent re-open: 200 (not 201), same URL, no second /pulls call.
        pulls_before = sum(1 for m, u in fake.calls if m == "POST" and u.endswith("/pulls"))
        with mock.patch(_REQUESTS_PATH, new=fake):
            again = api_client.post(open_url, {}, format="json")
        assert again.status_code == 200, again.data
        assert again.data["data"]["url"] == pr["url"]
        pulls_after = sum(1 for m, u in fake.calls if m == "POST" and u.endswith("/pulls"))
        assert pulls_after == pulls_before, "a re-approve opened a SECOND draft PR"

    def test_open_draft_pr_without_a_connection_is_a_typed_409(self, api_client, workspace_factory, team_factory):
        """The chain's front door fails closed: no VcsConnection → typed
        ``no_github_connection`` 409, and GitHub is never contacted."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _capability_agent(workspace, owner)
        api_client.force_authenticate(owner)
        fake = _FakeGitHubWithUser()

        open_url = f"/integrations/workspaces/{workspace.id}/findings/{task.id}/open-draft-pr/"
        with mock.patch(_REQUESTS_PATH, new=fake):
            resp = api_client.post(open_url, {}, format="json")

        assert resp.status_code == 409, resp.data
        assert resp.data["reason"] == "no_github_connection"
        assert fake.calls == []
        assert VcsConnection.objects.filter(workspace=workspace).count() == 0
        task.refresh_from_db()
        assert "draft_pr" not in task.metadata["payload"]
        assert Task.objects.get(id=task.id).metadata["triage"]["status"] == "triaged"
