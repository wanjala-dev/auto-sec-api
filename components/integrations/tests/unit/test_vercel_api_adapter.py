"""VercelApiAdapter — status-code mapping + secret hygiene (ADR 0021 D2).

Stubs ``requests.get`` at the adapter module's namespace; no live Vercel API.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests as requests_lib

from components.integrations.infrastructure.adapters.vercel import vercel_api_adapter
from components.integrations.infrastructure.adapters.vercel.vercel_api_adapter import VercelApiAdapter

pytestmark = pytest.mark.unit

_TOKEN = "vc_secret_token_value"


def _response(status_code=200, payload=None):
    return SimpleNamespace(status_code=status_code, json=lambda: payload or {})


@pytest.fixture
def requests_get(monkeypatch):
    calls = {}

    def _install(response=None, exc=None):
        def _get(url, headers=None, timeout=None):
            calls["url"] = url
            calls["headers"] = headers
            if exc is not None:
                raise exc
            return response

        monkeypatch.setattr(vercel_api_adapter.requests, "get", _get)
        return calls

    return _install


class TestVerifyToken:
    def test_ok_on_200(self, requests_get):
        calls = requests_get(_response(200, {"user": {"id": "u1"}}))
        health = VercelApiAdapter(_TOKEN).verify_token()
        assert health.ok is True
        assert calls["url"].endswith("/v2/user")
        assert calls["headers"]["Authorization"] == f"Bearer {_TOKEN}"

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_auth_failures_map_to_safe_reasons(self, requests_get, status):
        requests_get(_response(status))
        health = VercelApiAdapter(_TOKEN).verify_token()
        assert health.ok is False
        assert health.detail
        assert _TOKEN not in health.detail  # the secret never leaks into a reason

    def test_network_failure_is_a_health_not_an_exception(self, requests_get):
        requests_get(exc=requests_lib.ConnectionError("boom"))
        health = VercelApiAdapter(_TOKEN).verify_token()
        assert health.ok is False
        assert "reachable" in health.detail


class TestGetTeam:
    def test_resolves_the_canonical_trio(self, requests_get):
        calls = requests_get(_response(200, {"id": "team_abc123", "slug": "acme", "name": "Acme"}))
        health, team = VercelApiAdapter(_TOKEN).get_team("acme")
        assert health.ok is True
        assert (team.id, team.slug, team.name) == ("team_abc123", "acme", "Acme")
        assert calls["url"].endswith("/v2/teams/acme")

    def test_forbidden_team_is_an_error(self, requests_get):
        requests_get(_response(403))
        health, team = VercelApiAdapter(_TOKEN).get_team("acme")
        assert health.ok is False and team is None

    def test_team_without_an_id_is_an_error(self, requests_get):
        requests_get(_response(200, {"slug": "acme"}))
        health, team = VercelApiAdapter(_TOKEN).get_team("acme")
        assert health.ok is False and team is None


class TestGetTokenExpiry:
    def test_reads_expires_at_millis(self, requests_get):
        requests_get(_response(200, {"token": {"expiresAt": 1767225600000}}))
        expiry = VercelApiAdapter(_TOKEN).get_token_expiry()
        assert expiry is not None and expiry.year == 2026

    def test_no_expiration_token_returns_none(self, requests_get):
        requests_get(_response(200, {"token": {}}))
        assert VercelApiAdapter(_TOKEN).get_token_expiry() is None

    def test_best_effort_never_raises(self, requests_get):
        requests_get(exc=requests_lib.ConnectionError("boom"))
        assert VercelApiAdapter(_TOKEN).get_token_expiry() is None
