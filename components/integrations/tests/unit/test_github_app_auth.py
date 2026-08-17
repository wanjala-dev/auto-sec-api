"""Unit tests for the GitHub App auth adapter (ADR 0010 D6 / Phase B).

The HTTP boundary (``requests.post``) is stubbed — no real GitHub call ever
fires. Covers the four surfaces: JWT claims/expiry, the installation-token
exchange + its ~55-minute cache (the JWT is never cached), the typed
revoked-installation error, the signed install state, and the webhook HMAC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest import mock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache

from components.integrations.infrastructure.adapters.vcs import github_app_auth as auth

_REQUESTS_POST = "components.integrations.infrastructure.adapters.vcs.github_app_auth.requests.post"

# One keypair for the whole module — RSA generation is the slow part.
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("ascii")
_PUBLIC_PEM = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode("ascii")
)


@pytest.fixture(autouse=True)
def _app_settings(settings):
    settings.GITHUB_APP_ID = "12345"
    settings.GITHUB_APP_PRIVATE_KEY = _PRIVATE_PEM
    settings.GITHUB_APP_WEBHOOK_SECRET = "whsec_test"
    settings.GITHUB_APP_SLUG = "auto-sec-dev"
    cache.clear()
    yield
    cache.clear()


def _token_response(status_code=201, token="ghs_installation_token"):
    payload = {"token": token, "expires_at": "2099-01-01T00:00:00Z"}
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload), json=lambda: payload)


def _error_response(status_code, message="boom"):
    payload = {"message": message}
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload), json=lambda: payload)


@pytest.mark.unit
class TestMintAppJwt:
    def test_claims_match_github_contract(self):
        now = int(time.time())
        token = auth.mint_app_jwt(now=now)
        decoded = pyjwt.decode(token, _PUBLIC_PEM, algorithms=["RS256"], options={"verify_exp": False})
        header = pyjwt.get_unverified_header(token)
        assert header["alg"] == "RS256"
        assert decoded["iss"] == "12345"
        # iat backdated 60s (clock drift), exp at the 10-minute maximum.
        assert decoded["iat"] == now - 60
        assert decoded["exp"] == now + 600

    def test_escaped_newline_pem_is_normalized(self, settings):
        settings.GITHUB_APP_PRIVATE_KEY = _PRIVATE_PEM.replace("\n", "\\n")
        token = auth.mint_app_jwt()
        assert pyjwt.decode(token, _PUBLIC_PEM, algorithms=["RS256"])["iss"] == "12345"

    def test_missing_credentials_raise_typed_error(self, settings):
        settings.GITHUB_APP_ID = ""
        with pytest.raises(auth.GitHubAppNotConfiguredError):
            auth.mint_app_jwt()

    def test_garbage_key_raises_typed_error_without_key_material(self, settings):
        settings.GITHUB_APP_PRIVATE_KEY = "not-a-pem"
        with pytest.raises(auth.GitHubAppNotConfiguredError) as excinfo:
            auth.mint_app_jwt()
        assert "not-a-pem" not in str(excinfo.value)


@pytest.mark.unit
class TestInstallationToken:
    def test_exchanges_jwt_for_installation_token(self):
        with mock.patch(_REQUESTS_POST, return_value=_token_response()) as post:
            token = auth.get_installation_token(9001)
        assert token == "ghs_installation_token"
        (url,) = post.call_args.args
        assert url.endswith("/app/installations/9001/access_tokens")
        # The exchange authenticates with the freshly-minted APP JWT.
        bearer = post.call_args.kwargs["headers"]["Authorization"]
        assert bearer.startswith("Bearer ")
        decoded = pyjwt.decode(
            bearer.removeprefix("Bearer "), _PUBLIC_PEM, algorithms=["RS256"], options={"verify_exp": False}
        )
        assert decoded["iss"] == "12345"

    def test_token_is_cached_per_installation(self):
        with mock.patch(_REQUESTS_POST, return_value=_token_response()) as post:
            first = auth.get_installation_token(9001)
            second = auth.get_installation_token(9001)
            # A DIFFERENT installation is a different cache key → its own exchange.
            auth.get_installation_token(9002)
        assert first == second
        assert post.call_count == 2

    def test_the_jwt_is_never_cached(self):
        # Two exchanges for the SAME installation after an invalidation must
        # each mint a fresh JWT — nothing app-JWT-shaped survives in the cache.
        with mock.patch(_REQUESTS_POST, return_value=_token_response()) as post:
            auth.get_installation_token(9001)
            auth.invalidate_installation_token(9001)
            with mock.patch.object(auth, "mint_app_jwt", wraps=auth.mint_app_jwt) as mint:
                auth.get_installation_token(9001)
        assert post.call_count == 2
        assert mint.call_count == 1  # re-minted, not read back from anywhere

    def test_force_refresh_bypasses_cache(self):
        with mock.patch(_REQUESTS_POST, return_value=_token_response()) as post:
            auth.get_installation_token(9001)
            auth.get_installation_token(9001, force_refresh=True)
        assert post.call_count == 2

    def test_deleted_installation_raises_revoked(self):
        with (
            mock.patch(_REQUESTS_POST, return_value=_error_response(404)),
            pytest.raises(auth.GitHubAppInstallationRevokedError) as excinfo,
        ):
            auth.get_installation_token(9001)
        assert excinfo.value.installation_id == "9001"
        assert excinfo.value.status_code == 404

    def test_suspended_installation_raises_revoked(self):
        with (
            mock.patch(_REQUESTS_POST, return_value=_error_response(403)),
            pytest.raises(auth.GitHubAppInstallationRevokedError),
        ):
            auth.get_installation_token(9001)

    def test_revoked_is_not_cached(self):
        # After a revocation error, a recovered installation must be re-probed.
        with (
            mock.patch(_REQUESTS_POST, return_value=_error_response(404)),
            pytest.raises(auth.GitHubAppInstallationRevokedError),
        ):
            auth.get_installation_token(9001)
        with mock.patch(_REQUESTS_POST, return_value=_token_response()) as post:
            assert auth.get_installation_token(9001) == "ghs_installation_token"
        assert post.call_count == 1

    def test_other_api_errors_raise_auth_error(self):
        with (
            mock.patch(_REQUESTS_POST, return_value=_error_response(500)),
            pytest.raises(auth.GitHubAppAuthError) as excinfo,
        ):
            auth.get_installation_token(9001)
        assert not isinstance(excinfo.value, auth.GitHubAppInstallationRevokedError)


@pytest.mark.unit
class TestInstallState:
    def test_round_trip(self):
        state = auth.sign_install_state(workspace_id="ws-1", user_id="user-1")
        assert auth.unsign_install_state(state) == {"workspace_id": "ws-1", "user_id": "user-1"}

    def test_tampered_state_is_invalid(self):
        state = auth.sign_install_state(workspace_id="ws-1", user_id="user-1")
        with pytest.raises(auth.InvalidInstallStateError) as excinfo:
            auth.unsign_install_state(state + "x")
        assert excinfo.value.reason == "invalid"

    def test_expired_state_is_expired(self):
        state = auth.sign_install_state(workspace_id="ws-1", user_id="user-1")
        with pytest.raises(auth.InvalidInstallStateError) as excinfo:
            auth.unsign_install_state(state, max_age=-1)
        assert excinfo.value.reason == "expired"

    def test_missing_fields_are_invalid(self):
        from django.core import signing

        state = signing.dumps({"workspace_id": "ws-1"}, salt="integrations.github_app.install_state")
        with pytest.raises(auth.InvalidInstallStateError):
            auth.unsign_install_state(state)

    def test_install_url_carries_slug_and_state(self):
        url = auth.build_install_url("some-state")
        assert url == "https://github.com/apps/auto-sec-dev/installations/new?state=some-state"

    def test_install_url_without_slug_raises(self, settings):
        settings.GITHUB_APP_SLUG = ""
        with pytest.raises(auth.GitHubAppNotConfiguredError):
            auth.build_install_url("s")


@pytest.mark.unit
class TestWebhookSignature:
    def _sign(self, body: bytes, secret: str = "whsec_test") -> str:
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_signature_verifies(self):
        body = b'{"action": "deleted"}'
        assert auth.verify_webhook_signature(body, self._sign(body)) is True

    def test_tampered_body_fails(self):
        assert auth.verify_webhook_signature(b'{"action": "x"}', self._sign(b'{"action": "y"}')) is False

    def test_missing_header_fails(self):
        assert auth.verify_webhook_signature(b"{}", None) is False
        assert auth.verify_webhook_signature(b"{}", "") is False

    def test_wrong_scheme_fails(self):
        body = b"{}"
        sha1 = "sha1=" + hmac.new(b"whsec_test", body, hashlib.sha1).hexdigest()
        assert auth.verify_webhook_signature(body, sha1) is False

    def test_missing_secret_fails_closed(self, settings):
        settings.GITHUB_APP_WEBHOOK_SECRET = ""
        body = b"{}"
        assert auth.verify_webhook_signature(body, self._sign(body)) is False
