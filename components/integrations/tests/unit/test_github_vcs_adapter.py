"""Unit tests for the GitHub VCS adapter's ``verify`` wording (ADR 0010).

The HTTP layer (``requests.request``) is stubbed so no real GitHub call fires.
Asserts the operator-facing ``VcsHealth.detail`` distinguishes an auth failure
(401/403) from a repo-not-found/not-granted failure (404), and that the token
never leaks into the message.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.infrastructure.adapters.vcs.github_vcs_adapter import GitHubVcsAdapter

_REQUESTS_PATH = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.requests.request"


def _resp(status_code: int, payload: dict | None = None):
    payload = payload or {"message": "boom"}
    return SimpleNamespace(status_code=status_code, text=__import__("json").dumps(payload), json=lambda: payload)


@pytest.mark.unit
class TestGitHubVcsAdapterVerifyWording:
    def test_401_reads_as_token_problem(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        with mock.patch(_REQUESTS_PATH, return_value=_resp(401)):
            health = adapter.verify("acme/app")
        assert health.ok is False
        assert "token invalid, expired, or lacks permission" in health.detail
        assert "acme/app" not in health.detail  # a 401 is about the token, not the repo
        assert "ghp_secret_token" not in health.detail

    def test_403_reads_as_token_problem(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        with mock.patch(_REQUESTS_PATH, return_value=_resp(403)):
            health = adapter.verify("acme/app")
        assert health.ok is False
        assert "token invalid, expired, or lacks permission" in health.detail

    def test_404_with_repo_reads_as_repo_not_granted(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        with mock.patch(_REQUESTS_PATH, return_value=_resp(404)):
            health = adapter.verify("acme/app")
        assert health.ok is False
        assert "acme/app not found or not granted to this token" in health.detail
        assert "fine-grained PATs" in health.detail
        assert "ghp_secret_token" not in health.detail

    def test_success_token_only(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, {"login": "acme-bot"})):
            health = adapter.verify(None)
        assert health.ok is True
        assert "ghp_secret_token" not in health.detail

    def test_success_with_repo(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, {"full_name": "acme/app"})):
            health = adapter.verify("acme/app")
        assert health.ok is True
        assert "acme/app accessible" in health.detail
