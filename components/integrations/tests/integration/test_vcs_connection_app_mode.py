"""Integration tests: app-mode VcsConnection rows (model, resource, verify).

Proves the two Phase-B model fields land with PAT rows untouched, the REST
resource exposes the credential surface without ever echoing a secret, and
``verify`` in app mode mints an installation token (never GET /user — an
installation token cannot call it) and records a revoked installation as a
named error on the row.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.ports.vcs_port import VcsHealth
from infrastructure.persistence.integrations.models import VcsConnection

_INSTALLATION_TOKEN = "components.integrations.infrastructure.adapters.vcs.github_app_auth.get_installation_token"
_ADAPTER = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.GitHubVcsAdapter"


def _base(workspace_id):
    return f"/integrations/workspaces/{workspace_id}/vcs-connections/"


@pytest.fixture
def owner_ws(workspace_factory):
    ws = workspace_factory()
    return ws, ws.workspace_owner


def _app_connection(workspace, **kwargs):
    defaults = {
        "provider": VcsConnection.Provider.GITHUB,
        "auth_mode": VcsConnection.AuthMode.GITHUB_APP,
        "installation_id": 9001,
        "name": "GitHub App",
        "repo_allowlist": ["acme/app"],
        "status": VcsConnection.Status.CONNECTED,
        "token_ciphertext": "",
    }
    defaults.update(kwargs)
    return VcsConnection.objects.create(workspace=workspace, **defaults)


@pytest.mark.django_db
class TestModelDefaults:
    def test_existing_pat_rows_default_to_pat_mode(self, owner_ws):
        ws, _ = owner_ws
        connection = VcsConnection.objects.create(
            workspace=ws, provider="github", repo_allowlist=["acme/app"], token_ciphertext="ct"
        )
        assert connection.auth_mode == VcsConnection.AuthMode.PAT
        assert connection.installation_id is None


@pytest.mark.django_db
class TestResourceSurface:
    def test_app_row_reads_as_credentialed_without_a_stored_token(self, api_client, owner_ws):
        ws, owner = owner_ws
        _app_connection(ws)
        api_client.force_authenticate(owner)
        resp = api_client.get(_base(ws.id))
        assert resp.status_code == 200
        (body,) = resp.data["data"]
        assert body["auth_mode"] == "github_app"
        assert body["installation_id"] == 9001
        # App mode stores no secret, but the connection IS credentialed.
        assert body["has_token"] is True
        assert "token" not in body
        assert "token_ciphertext" not in body

    def test_pat_row_keeps_its_existing_shape(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"provider": "github", "repo_allowlist": ["acme/app"], "token": "ghp_secret"},
            format="json",
        )
        assert created.status_code == 201
        body = created.data["data"]
        assert body["auth_mode"] == "pat"
        assert body["installation_id"] is None
        assert body["has_token"] is True


@pytest.mark.django_db
class TestVerifyAppMode:
    def test_verify_mints_a_token_and_probes_repos_only(self, api_client, owner_ws):
        ws, owner = owner_ws
        connection = _app_connection(ws, repo_allowlist=["acme/app", "acme/infra"])
        api_client.force_authenticate(owner)

        with (
            mock.patch(_INSTALLATION_TOKEN, return_value="ghs_short_lived") as mint,
            mock.patch(_ADAPTER) as adapter_cls,
        ):
            adapter = adapter_cls.return_value
            adapter.verify.return_value = VcsHealth(ok=True, detail="ok")
            resp = api_client.post(f"{_base(ws.id)}{connection.id}/verify/")

        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["status"] == "connected"
        mint.assert_called_once_with(9001)
        adapter_cls.assert_called_once_with("ghs_short_lived")
        # No bare-token probe: GET /user is a user-token endpoint an
        # installation token cannot call. Only the allowlisted repos are probed.
        probed = [call.args[0] for call in adapter.verify.call_args_list]
        assert probed == ["acme/app", "acme/infra"]
        connection.refresh_from_db()
        assert connection.last_verified_at is not None

    def test_verify_records_a_revoked_installation(self, api_client, owner_ws):
        from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
            GitHubAppInstallationRevokedError,
        )

        ws, owner = owner_ws
        connection = _app_connection(ws)
        api_client.force_authenticate(owner)
        with mock.patch(
            _INSTALLATION_TOKEN,
            side_effect=GitHubAppInstallationRevokedError(
                "GitHub App installation 9001 is revoked or suspended on GitHub.",
                installation_id="9001",
                status_code=404,
            ),
        ):
            resp = api_client.post(f"{_base(ws.id)}{connection.id}/verify/")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "error"
        connection.refresh_from_db()
        assert "revoked or suspended" in connection.last_error

    def test_verify_names_a_missing_installation(self, api_client, owner_ws):
        ws, owner = owner_ws
        connection = _app_connection(ws, installation_id=None)
        api_client.force_authenticate(owner)
        resp = api_client.post(f"{_base(ws.id)}{connection.id}/verify/")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "error"
        connection.refresh_from_db()
        assert "no GitHub App installation" in connection.last_error


@pytest.mark.django_db
class TestOpenDraftPrWiring:
    def test_composition_root_wires_the_auth_strategy(self):
        # The provider-built use cases carry the per-connection resolver, so an
        # app-mode connection's draft PR mints an installation token instead of
        # reading a PAT (the resolver's own unit tests prove that behavior).
        from components.integrations.application.providers.vcs_provider import (
            get_check_pr_merged_use_case,
            get_open_draft_pr_use_case,
            get_vcs_connection_service,
            resolve_vcs_connection_token,
        )

        assert get_open_draft_pr_use_case()._resolve_token is resolve_vcs_connection_token
        assert get_check_pr_merged_use_case()._resolve_token is resolve_vcs_connection_token
        assert get_vcs_connection_service()._resolve_token is resolve_vcs_connection_token
