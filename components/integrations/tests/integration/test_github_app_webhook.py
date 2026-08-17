"""Integration tests for the GitHub App webhook receiver (ADR 0010 Phase B).

Signature-first: an unverified POST must 401 before any body parsing, and an
unconfigured secret is a loud 503, never a silent accept. Celery runs eager in
tests, so a verified event's side effects (revocation sync, repo-removal note)
are asserted end-to-end; the merged-PR fan-out asserts the dispatch onto the
EXISTING reconcile seam (by task name) rather than re-running the reconciler.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest import mock

import pytest

from infrastructure.persistence.integrations.models import VcsConnection

_WEBHOOK = "/integrations/vcs/github-app/webhook/"
_SECRET = "whsec_test"


@pytest.fixture(autouse=True)
def _app_settings(settings):
    settings.GITHUB_APP_ID = "12345"
    settings.GITHUB_APP_WEBHOOK_SECRET = _SECRET
    yield


def _post(api_client, event: str, payload: dict, *, secret: str | None = _SECRET, signature: str | None = None):
    body = json.dumps(payload).encode("utf-8")
    headers = {"HTTP_X_GITHUB_EVENT": event, "HTTP_X_GITHUB_DELIVERY": "d-1"}
    if signature is not None:
        headers["HTTP_X_HUB_SIGNATURE_256"] = signature
    elif secret is not None:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["HTTP_X_HUB_SIGNATURE_256"] = f"sha256={digest}"
    return api_client.post(_WEBHOOK, data=body, content_type="application/json", **headers)


def _app_connection(workspace, installation_id=9001, **kwargs):
    defaults = {
        "provider": VcsConnection.Provider.GITHUB,
        "auth_mode": VcsConnection.AuthMode.GITHUB_APP,
        "installation_id": installation_id,
        "name": "GitHub App",
        "status": VcsConnection.Status.CONNECTED,
        "token_ciphertext": "",
    }
    defaults.update(kwargs)
    return VcsConnection.objects.create(workspace=workspace, **defaults)


@pytest.mark.django_db
class TestSignatureGate:
    def test_bad_signature_is_401(self, api_client, workspace_factory):
        ws = workspace_factory()
        _app_connection(ws)
        resp = _post(
            api_client,
            "installation",
            {"action": "deleted", "installation": {"id": 9001}},
            signature="sha256=" + "0" * 64,
        )
        assert resp.status_code == 401
        # Nothing happened: the connection is untouched.
        assert VcsConnection.objects.get(workspace=ws).status == VcsConnection.Status.CONNECTED

    def test_missing_signature_is_401(self, api_client):
        resp = _post(api_client, "installation", {"action": "deleted"}, secret=None)
        assert resp.status_code == 401

    def test_unconfigured_secret_is_503(self, api_client, settings):
        settings.GITHUB_APP_WEBHOOK_SECRET = ""
        resp = _post(api_client, "installation", {"action": "deleted"})
        assert resp.status_code == 503

    def test_invalid_json_after_valid_signature_is_400(self, api_client):
        body = b"not-json"
        digest = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
        resp = api_client.post(
            _WEBHOOK,
            data=body,
            content_type="application/json",
            HTTP_X_GITHUB_EVENT="installation",
            HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}",
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestInstallationRevocationSync:
    def test_deleted_installation_deactivates_the_connection(self, api_client, workspace_factory):
        ws = workspace_factory()
        connection = _app_connection(ws, installation_id=9001)
        resp = _post(api_client, "installation", {"action": "deleted", "installation": {"id": 9001}})
        assert resp.status_code == 202
        connection.refresh_from_db()
        assert connection.status == VcsConnection.Status.DISABLED
        assert "deleted on GitHub" in connection.last_error

    def test_suspended_installation_deactivates_the_connection(self, api_client, workspace_factory):
        ws = workspace_factory()
        connection = _app_connection(ws, installation_id=9001)
        resp = _post(api_client, "installation", {"action": "suspend", "installation": {"id": 9001}})
        assert resp.status_code == 202
        connection.refresh_from_db()
        assert connection.status == VcsConnection.Status.DISABLED
        assert "suspended on GitHub" in connection.last_error

    def test_only_the_matching_installation_is_touched(self, api_client, workspace_factory):
        ws_a, ws_b = workspace_factory(), workspace_factory()
        hit = _app_connection(ws_a, installation_id=9001)
        other = _app_connection(ws_b, installation_id=7777)
        _post(api_client, "installation", {"action": "deleted", "installation": {"id": 9001}})
        hit.refresh_from_db()
        other.refresh_from_db()
        assert hit.status == VcsConnection.Status.DISABLED
        assert other.status == VcsConnection.Status.CONNECTED

    def test_cached_installation_token_is_dropped(self, api_client, workspace_factory):
        from django.core.cache import cache

        from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
            _token_cache_key,
        )

        ws = workspace_factory()
        _app_connection(ws, installation_id=9001)
        cache.set(_token_cache_key("9001"), "ghs_stale", 300)
        _post(api_client, "installation", {"action": "deleted", "installation": {"id": 9001}})
        assert cache.get(_token_cache_key("9001")) is None

    def test_created_action_is_ignored(self, api_client):
        # Binding happens ONLY via the signed-state setup flow — a bare install
        # from GitHub's UI has no workspace to bind to.
        resp = _post(api_client, "installation", {"action": "created", "installation": {"id": 9001}})
        assert resp.status_code == 204


@pytest.mark.django_db
class TestRepositoriesRemoved:
    def test_removed_repos_are_noted_without_deactivating(self, api_client, workspace_factory):
        ws = workspace_factory()
        connection = _app_connection(ws, installation_id=9001, repo_allowlist=["acme/app"])
        resp = _post(
            api_client,
            "installation_repositories",
            {
                "action": "removed",
                "installation": {"id": 9001},
                "repositories_removed": [{"full_name": "acme/app"}],
            },
        )
        assert resp.status_code == 202
        connection.refresh_from_db()
        assert connection.status == VcsConnection.Status.CONNECTED  # installation itself is intact
        assert "acme/app" in connection.last_error
        assert "repositories removed" in connection.last_error

    def test_added_action_is_ignored(self, api_client):
        resp = _post(
            api_client,
            "installation_repositories",
            {"action": "added", "installation": {"id": 9001}, "repositories_added": [{"full_name": "a/b"}]},
        )
        assert resp.status_code == 204


@pytest.mark.django_db
class TestMergedPullRequest:
    _SEND_TASK = "components.integrations.infrastructure.tasks.github_app_webhook_tasks.current_app"

    def _merged_payload(self, repo="acme/app"):
        return {
            "action": "closed",
            "pull_request": {"merged": True, "number": 7},
            "repository": {"full_name": repo},
        }

    def test_merged_pr_feeds_the_existing_reconcile_seam(self, api_client, workspace_factory):
        ws = workspace_factory()
        _app_connection(ws, installation_id=9001, repo_allowlist=["acme/app"])
        with mock.patch(self._SEND_TASK) as celery_app:
            resp = _post(api_client, "pull_request", self._merged_payload())
        assert resp.status_code == 202
        celery_app.send_task.assert_called_once_with(
            "remediation.reconcile_applied_remediations", kwargs={"workspace_id": str(ws.id)}
        )

    def test_workspaces_not_allowlisting_the_repo_are_not_dispatched(self, api_client, workspace_factory):
        ws = workspace_factory()
        _app_connection(ws, installation_id=9001, repo_allowlist=["other/repo"])
        with mock.patch(self._SEND_TASK) as celery_app:
            resp = _post(api_client, "pull_request", self._merged_payload())
        assert resp.status_code == 202
        celery_app.send_task.assert_not_called()

    def test_pat_connections_also_ride_the_seam(self, api_client, workspace_factory):
        # The merged-PR accelerator keys on the repo allowlist, not the auth
        # mode — a PAT workspace's reconcile is sped up identically.
        ws = workspace_factory()
        VcsConnection.objects.create(
            workspace=ws,
            provider=VcsConnection.Provider.GITHUB,
            repo_allowlist=["acme/app"],
            token_ciphertext="ct",
            status=VcsConnection.Status.CONNECTED,
        )
        with mock.patch(self._SEND_TASK) as celery_app:
            _post(api_client, "pull_request", self._merged_payload())
        celery_app.send_task.assert_called_once()

    def test_closed_without_merge_is_ignored(self, api_client, workspace_factory):
        ws = workspace_factory()
        _app_connection(ws, installation_id=9001, repo_allowlist=["acme/app"])
        with mock.patch(self._SEND_TASK) as celery_app:
            resp = _post(
                api_client,
                "pull_request",
                {
                    "action": "closed",
                    "pull_request": {"merged": False, "number": 7},
                    "repository": {"full_name": "acme/app"},
                },
            )
        assert resp.status_code == 204
        celery_app.send_task.assert_not_called()


@pytest.mark.django_db
class TestUnknownEvents:
    def test_unknown_event_is_204(self, api_client):
        assert _post(api_client, "star", {"action": "created"}).status_code == 204

    def test_unknown_installation_action_is_204(self, api_client):
        resp = _post(api_client, "installation", {"action": "new_permissions_accepted", "installation": {"id": 1}})
        assert resp.status_code == 204
