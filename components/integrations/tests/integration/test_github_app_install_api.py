"""Integration tests for the GitHub App install + setup flow (ADR 0010 Phase B).

The security-critical piece is the SIGNED STATE: the setup redirect is a browser
GET with no JWT, so the state is the whole authorization. Unsigned / tampered /
expired states must 4xx and bind nothing, and the workspace binding comes ONLY
from the state — never from the query string (mass-assignment guard).
"""

from __future__ import annotations

import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest

from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
    sign_install_state,
    unsign_install_state,
)
from infrastructure.persistence.integrations.models import VcsConnection

_SETUP = "/integrations/vcs/github-app/setup/"


def _install_url(workspace_id):
    return f"/integrations/workspaces/{workspace_id}/vcs/github-app/install/"


@pytest.fixture(autouse=True)
def _app_settings(settings):
    settings.GITHUB_APP_ID = "12345"
    settings.GITHUB_APP_SLUG = "auto-sec-dev"
    yield


@pytest.fixture
def owner_ws(workspace_factory):
    ws = workspace_factory()
    return ws, ws.workspace_owner


@pytest.mark.django_db
class TestInstallEndpoint:
    def test_install_url_carries_signed_state_for_this_workspace(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_install_url(ws.id))
        assert resp.status_code == 200, resp.data
        install_url = resp.data["data"]["install_url"]
        assert install_url.startswith("https://github.com/apps/auto-sec-dev/installations/new?state=")
        state = parse_qs(urlparse(install_url).query)["state"][0]
        payload = unsign_install_state(state)
        assert payload["workspace_id"] == str(ws.id)
        assert payload["user_id"] == str(owner.id)

    def test_requires_authentication(self, api_client, owner_ws):
        ws, _ = owner_ws
        assert api_client.post(_install_url(ws.id)).status_code in (401, 403)

    def test_non_member_is_denied(self, api_client, owner_ws, user_factory):
        ws, _ = owner_ws
        api_client.force_authenticate(user_factory())
        assert api_client.post(_install_url(ws.id)).status_code == 403

    @pytest.mark.real_feature_flags
    def test_flag_off_is_403(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_install_url(ws.id))
        assert resp.status_code == 403
        assert resp.data["error"] == "vcs_github_app_not_enabled"

    def test_unregistered_app_is_an_honest_409(self, api_client, owner_ws, settings):
        settings.GITHUB_APP_SLUG = ""
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_install_url(ws.id))
        assert resp.status_code == 409
        assert resp.data["error"] == "github_app_not_configured"


@pytest.mark.django_db
class TestSetupEndpoint:
    def _state_for(self, ws, owner) -> str:
        return sign_install_state(workspace_id=str(ws.id), user_id=str(owner.id))

    def test_valid_state_binds_the_installation(self, api_client, owner_ws):
        ws, owner = owner_ws
        resp = api_client.get(
            _SETUP, {"state": self._state_for(ws, owner), "installation_id": "9001", "setup_action": "install"}
        )
        # Test settings carry a frontend URL → the browser is bounced to the HUD.
        assert resp.status_code == 302
        assert "github_app=connected" in resp["Location"]
        connection = VcsConnection.objects.get(workspace_id=ws.id)
        assert connection.auth_mode == VcsConnection.AuthMode.GITHUB_APP
        assert connection.installation_id == 9001
        assert connection.status == VcsConnection.Status.CONNECTED
        assert connection.token_ciphertext == ""  # app mode stores NO secret
        assert str(connection.created_by_id) == str(owner.id)

    def test_rebind_is_idempotent_and_reinstall_repoints(self, api_client, owner_ws):
        ws, owner = owner_ws
        state = self._state_for(ws, owner)
        api_client.get(_SETUP, {"state": state, "installation_id": "9001"})
        api_client.get(_SETUP, {"state": state, "installation_id": "9001"})
        assert VcsConnection.objects.filter(workspace_id=ws.id).count() == 1
        # Uninstall → reinstall arrives with a NEW installation id: re-point, not duplicate.
        api_client.get(_SETUP, {"state": state, "installation_id": "9002"})
        connection = VcsConnection.objects.get(workspace_id=ws.id)
        assert connection.installation_id == 9002

    def test_missing_state_is_400(self, api_client):
        resp = api_client.get(_SETUP, {"installation_id": "9001"})
        assert resp.status_code == 400
        assert resp.data["error"] == "install_state_invalid"
        assert VcsConnection.objects.count() == 0

    def test_tampered_state_is_400_and_binds_nothing(self, api_client, owner_ws):
        ws, owner = owner_ws
        resp = api_client.get(_SETUP, {"state": self._state_for(ws, owner) + "x", "installation_id": "9001"})
        assert resp.status_code == 400
        assert resp.data["error"] == "install_state_invalid"
        assert VcsConnection.objects.count() == 0

    def test_expired_state_is_403_and_binds_nothing(self, api_client, owner_ws):
        ws, owner = owner_ws
        # Mint the state 16 minutes in the past (max age is 15).
        with mock.patch("time.time", return_value=time.time() - 16 * 60):
            stale = self._state_for(ws, owner)
        resp = api_client.get(_SETUP, {"state": stale, "installation_id": "9001"})
        assert resp.status_code == 403
        assert resp.data["error"] == "install_state_expired"
        assert VcsConnection.objects.count() == 0

    def test_workspace_comes_only_from_the_state(self, api_client, owner_ws, workspace_factory):
        # Mass-assignment guard: a workspace_id in the query string must be
        # ignored — a state minted for workspace A can never bind workspace B.
        ws_a, owner_a = owner_ws
        ws_b = workspace_factory()
        resp = api_client.get(
            _SETUP,
            {
                "state": self._state_for(ws_a, owner_a),
                "installation_id": "9001",
                "workspace_id": str(ws_b.id),
            },
        )
        assert resp.status_code == 302
        assert VcsConnection.objects.filter(workspace_id=ws_a.id).count() == 1
        assert VcsConnection.objects.filter(workspace_id=ws_b.id).count() == 0

    def test_missing_installation_id_is_400(self, api_client, owner_ws):
        ws, owner = owner_ws
        resp = api_client.get(_SETUP, {"state": self._state_for(ws, owner)})
        assert resp.status_code == 400
        assert resp.data["error"] == "installation_id_missing"

    def test_non_numeric_installation_id_is_400(self, api_client, owner_ws):
        ws, owner = owner_ws
        resp = api_client.get(_SETUP, {"state": self._state_for(ws, owner), "installation_id": "abc"})
        assert resp.status_code == 400

    @pytest.mark.real_feature_flags
    def test_flag_off_is_403(self, api_client, owner_ws):
        ws, owner = owner_ws
        resp = api_client.get(_SETUP, {"state": self._state_for(ws, owner), "installation_id": "9001"})
        assert resp.status_code == 403
        assert resp.data["error"] == "vcs_github_app_not_enabled"
        assert VcsConnection.objects.count() == 0
