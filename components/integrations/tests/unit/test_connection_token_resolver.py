"""Unit tests for the per-connection VCS auth strategy (ADR 0010 Phase B).

The load-bearing assertion: in app mode NO user PAT is ever read — the stored
ciphertext is ignored even when present, and the token comes exclusively from
the GitHub App installation exchange.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.infrastructure.adapters.connection_token_resolver import (
    resolve_connection_token,
)

_DECRYPT = "components.integrations.infrastructure.adapters.secret_envelope.decrypt_secret"
_INSTALLATION_TOKEN = "components.integrations.infrastructure.adapters.vcs.github_app_auth.get_installation_token"


def _connection(**kwargs):
    defaults = {
        "auth_mode": "pat",
        "installation_id": None,
        "token_ciphertext": "",
        "provider": "github",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
class TestPatMode:
    def test_pat_rows_decrypt_the_stored_ciphertext(self):
        connection = _connection(token_ciphertext="ct")
        with (
            mock.patch(_DECRYPT, return_value="ghp_pat") as decrypt,
            mock.patch(_INSTALLATION_TOKEN) as mint,
        ):
            assert resolve_connection_token(connection) == "ghp_pat"
        decrypt.assert_called_once_with("ct")
        mint.assert_not_called()

    def test_missing_auth_mode_defaults_to_pat(self):
        # Pre-Phase-B rows (and fakes) without the attribute keep working.
        connection = SimpleNamespace(token_ciphertext="ct", provider="github")
        with mock.patch(_DECRYPT, return_value="ghp_pat"):
            assert resolve_connection_token(connection) == "ghp_pat"

    def test_none_connection_is_empty(self):
        assert resolve_connection_token(None) == ""


@pytest.mark.unit
class TestGitHubAppMode:
    def test_app_rows_mint_installation_tokens(self):
        connection = _connection(auth_mode="github_app", installation_id=9001)
        with mock.patch(_INSTALLATION_TOKEN, return_value="ghs_short_lived") as mint:
            assert resolve_connection_token(connection) == "ghs_short_lived"
        mint.assert_called_once_with(9001)

    def test_app_mode_never_reads_a_user_pat(self):
        # Even with a leftover PAT ciphertext on the row, app mode must not
        # touch it — the PR is authored by the app's bot, not a user identity.
        connection = _connection(auth_mode="github_app", installation_id=9001, token_ciphertext="stale-pat-ciphertext")
        with (
            mock.patch(_DECRYPT, side_effect=AssertionError("user PAT read in app mode")) as decrypt,
            mock.patch(_INSTALLATION_TOKEN, return_value="ghs_short_lived"),
        ):
            assert resolve_connection_token(connection) == "ghs_short_lived"
        decrypt.assert_not_called()

    def test_app_mode_without_installation_is_no_credential(self):
        connection = _connection(auth_mode="github_app", installation_id=None)
        with mock.patch(_INSTALLATION_TOKEN) as mint:
            assert resolve_connection_token(connection) == ""
        mint.assert_not_called()

    def test_typed_revocation_error_propagates(self):
        from components.integrations.infrastructure.adapters.vcs.github_app_auth import (
            GitHubAppInstallationRevokedError,
        )

        connection = _connection(auth_mode="github_app", installation_id=9001)
        with mock.patch(
            _INSTALLATION_TOKEN,
            side_effect=GitHubAppInstallationRevokedError("revoked", installation_id="9001", status_code=404),
        ), pytest.raises(GitHubAppInstallationRevokedError):
            resolve_connection_token(connection)
