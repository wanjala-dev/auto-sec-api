"""Integration tests for the VcsConnection CRUD + verify API (ADR 0010 Phase 3)."""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.ports.vcs_port import VcsHealth

_ADAPTER = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.GitHubVcsAdapter"


def _base(workspace_id):
    return f"/integrations/workspaces/{workspace_id}/vcs-connections/"


@pytest.fixture
def owner_ws(workspace_factory):
    ws = workspace_factory()
    return ws, ws.workspace_owner


@pytest.mark.django_db
class TestVcsConnectionCrud:
    def test_list_starts_empty(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.get(_base(ws.id))
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_create_github_connection(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id),
            {"provider": "github", "name": "prod org", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        )
        assert resp.status_code == 201, resp.data
        body = resp.data["data"]
        assert body["provider"] == "github"
        assert body["repo_allowlist"] == ["acme/app"]
        assert body["status"] == "connected"
        # The token is NEVER echoed back — only has_token.
        assert body["has_token"] is True
        assert "token" not in body

    def test_repo_root_round_trips_through_create_and_patch(self, api_client, owner_ws):
        # The monorepo override (repo_root) is settable on create, exposed read-only on
        # the resource, and updatable via PATCH — auto-detect works without it, but an
        # operator can pin the subdirectory their app lives under.
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret", "repo_root": "api-v2.0"},
            format="json",
        )
        assert created.status_code == 201, created.data
        assert created.data["data"]["repo_root"] == "api-v2.0"

        detail = f"{_base(ws.id)}{created.data['data']['id']}/"
        patched = api_client.patch(detail, {"repo_root": "backend"}, format="json")
        assert patched.data["data"]["repo_root"] == "backend"

    def test_repo_root_rejects_path_traversal_on_create(self, api_client, owner_ws):
        # A `..`-bearing repo_root would escape the repo-scoped GitHub URL — the DTO
        # boundary rejects it with a 400 before it ever reaches persistence.
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        for bad in ("../../../etc", "/etc/passwd", "api-v2.0/../..", "foo/./bar"):
            resp = api_client.post(
                _base(ws.id),
                {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret", "repo_root": bad},
                format="json",
            )
            assert resp.status_code == 400, (bad, resp.data)
            assert "repo_root" in resp.data["error"]

    def test_repo_root_rejects_path_traversal_on_patch(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        ).data["data"]
        detail = f"{_base(ws.id)}{created['id']}/"
        resp = api_client.patch(detail, {"repo_root": "../../../etc"}, format="json")
        assert resp.status_code == 400
        assert "repo_root" in resp.data["error"]

    def test_repo_root_defaults_empty(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        )
        assert resp.data["data"]["repo_root"] == ""

    def test_commit_identity_defaults_pat_owner(self, api_client, owner_ws):
        # An unspecified commit_identity defaults to pat_owner (unchanged behavior).
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        )
        assert resp.status_code == 201, resp.data
        assert resp.data["data"]["commit_identity"] == "pat_owner"
        assert resp.data["data"]["commit_author_name"] == ""
        assert resp.data["data"]["commit_author_email"] == ""

    def test_commit_identity_custom_round_trips(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {
                "provider": "github",
                "repo_allowlist": ["acme/app"],
                "token": "ghp_secret",
                "commit_identity": "custom",
                "commit_author_name": "Auto-Sec Bot",
                "commit_author_email": "bot@autosec.example",
            },
            format="json",
        )
        assert created.status_code == 201, created.data
        body = created.data["data"]
        assert body["commit_identity"] == "custom"
        assert body["commit_author_name"] == "Auto-Sec Bot"
        assert body["commit_author_email"] == "bot@autosec.example"

        detail = f"{_base(ws.id)}{body['id']}/"
        patched = api_client.patch(detail, {"commit_identity": "operator"}, format="json")
        assert patched.status_code == 200, patched.data
        assert patched.data["data"]["commit_identity"] == "operator"

    def test_commit_identity_custom_requires_name_and_email(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id),
            {
                "provider": "github",
                "repo_allowlist": ["acme/app"],
                "token": "ghp_secret",
                "commit_identity": "custom",
                "commit_author_name": "Auto-Sec Bot",
                # email intentionally omitted
            },
            format="json",
        )
        assert resp.status_code == 400
        assert "commit_identity" in resp.data["error"]

    def test_commit_identity_rejects_unknown_value(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id),
            {"provider": "github", "token": "ghp_secret", "commit_identity": "bogus"},
            format="json",
        )
        assert resp.status_code == 400
        assert "commit_identity" in resp.data["error"]

    def test_patch_to_custom_without_email_is_rejected(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        ).data["data"]
        detail = f"{_base(ws.id)}{created['id']}/"
        resp = api_client.patch(detail, {"commit_identity": "custom"}, format="json")
        assert resp.status_code == 400
        assert "commit_identity" in resp.data["error"]

    def test_create_rejects_missing_token(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_base(ws.id), {"provider": "github", "repo_allowlist": ["acme/app"]}, format="json")
        assert resp.status_code == 400
        assert "token" in resp.data["error"]

    def test_create_rejects_unavailable_provider(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_base(ws.id), {"provider": "gitlab", "token": "glpat_x"}, format="json")
        assert resp.status_code == 400
        assert "not available" in resp.data["error"]

    def test_patch_disable_then_enable_and_allowlist(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        ).data["data"]
        detail = f"{_base(ws.id)}{created['id']}/"

        disabled = api_client.patch(detail, {"status": "disabled"}, format="json")
        assert disabled.data["data"]["status"] == "disabled"
        enabled = api_client.patch(
            detail, {"status": "connected", "repo_allowlist": ["acme/app", "acme/api"]}, format="json"
        )
        assert enabled.data["data"]["status"] == "connected"
        assert enabled.data["data"]["repo_allowlist"] == ["acme/app", "acme/api"]

    def test_patch_rejects_system_owned_status(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(_base(ws.id), {"provider": "github", "token": "ghp_secret"}, format="json").data[
            "data"
        ]
        resp = api_client.patch(f"{_base(ws.id)}{created['id']}/", {"status": "error"}, format="json")
        assert resp.status_code == 400

    def test_delete_removes_connection(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(_base(ws.id), {"provider": "github", "token": "ghp_secret"}, format="json").data[
            "data"
        ]
        resp = api_client.delete(f"{_base(ws.id)}{created['id']}/")
        assert resp.status_code == 200
        assert api_client.get(_base(ws.id)).data["data"] == []

    def test_anonymous_is_denied(self, api_client, owner_ws):
        ws, _owner = owner_ws
        resp = api_client.get(_base(ws.id))
        assert resp.status_code in (401, 403)


@pytest.mark.django_db
class TestVcsConnectionVerify:
    def _create(self, api_client, ws):
        return api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        ).data["data"]

    def test_verify_success_marks_connected(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = self._create(api_client, ws)

        url = f"{_base(ws.id)}{created['id']}/verify/"
        with mock.patch(f"{_ADAPTER}.verify", return_value=VcsHealth(ok=True)):
            resp = api_client.post(url, {}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "connected"
        assert resp.data["data"]["last_verified_at"] is not None

    def test_verify_failure_marks_error(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = self._create(api_client, ws)

        url = f"{_base(ws.id)}{created['id']}/verify/"
        with mock.patch(f"{_ADAPTER}.verify", return_value=VcsHealth(ok=False, detail="token invalid")):
            resp = api_client.post(url, {}, format="json")
        assert resp.data["data"]["status"] == "error"
        assert "token invalid" in resp.data["data"]["last_error"]

    def _create_multi(self, api_client, ws, allowlist):
        return api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": allowlist, "token": "ghp_secret"},
            format="json",
        ).data["data"]

    def test_verify_all_repos_accessible_marks_connected(self, api_client, owner_ws):
        # A 2-repo allowlist where the token probe AND both repos are reachable → connected.
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = self._create_multi(api_client, ws, ["acme/app", "acme/api"])

        url = f"{_base(ws.id)}{created['id']}/verify/"
        with mock.patch(f"{_ADAPTER}.verify", return_value=VcsHealth(ok=True)):
            resp = api_client.post(url, {}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "connected"
        assert resp.data["data"]["last_verified_at"] is not None

    def test_verify_one_repo_inaccessible_names_it(self, api_client, owner_ws):
        # Token is valid, but one of two repos 404s → error that NAMES the blocked repo,
        # not a silent pass masked by the accessible sibling.
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = self._create_multi(api_client, ws, ["acme/app", "acme/secret"])

        def _verify(repo=None):
            if repo == "acme/secret":
                return VcsHealth(ok=False, detail="GitHub repo acme/secret not found or not granted to this token.")
            return VcsHealth(ok=True)

        url = f"{_base(ws.id)}{created['id']}/verify/"
        with mock.patch(f"{_ADAPTER}.verify", side_effect=_verify):
            resp = api_client.post(url, {}, format="json")
        assert resp.data["data"]["status"] == "error"
        last_error = resp.data["data"]["last_error"]
        assert "acme/secret" in last_error
        assert "no access or unreachable" in last_error
        # The accessible repo is NOT listed as blocked.
        assert "acme/app" not in last_error

    def test_verify_invalid_token_reports_token_error(self, api_client, owner_ws):
        # The token probe (repo=None) fails → single root-cause message, repos never probed.
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = self._create_multi(api_client, ws, ["acme/app", "acme/api"])

        def _verify(repo=None):
            if repo is None:
                return VcsHealth(ok=False, detail="GitHub token invalid, expired, or lacks permission.")
            raise AssertionError("repos must not be probed when the token itself is invalid")

        url = f"{_base(ws.id)}{created['id']}/verify/"
        with mock.patch(f"{_ADAPTER}.verify", side_effect=_verify):
            resp = api_client.post(url, {}, format="json")
        assert resp.data["data"]["status"] == "error"
        assert "token invalid" in resp.data["data"]["last_error"]
