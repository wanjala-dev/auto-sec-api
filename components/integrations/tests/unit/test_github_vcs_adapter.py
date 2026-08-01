"""Unit tests for the GitHub VCS adapter's ``verify`` wording (ADR 0010).

The HTTP layer (``requests.request``) is stubbed so no real GitHub call fires.
Asserts the operator-facing ``VcsHealth.detail`` distinguishes an auth failure
(401/403) from a repo-not-found/not-granted failure (404), and that the token
never leaks into the message.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.application.ports.vcs_port import VcsApiError
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


class _FakeTreeGitHub:
    """Scripted ``requests.request`` for the tree-listing path (ref → sha → tree)."""

    def __init__(self, tree: list[dict], *, truncated: bool = False, sha: str = "treesha"):
        self._tree = tree
        self._truncated = truncated
        self._sha = sha
        self.calls: list[str] = []

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = url.split("api.github.com")[-1]
        self.calls.append(path)
        if "/git/ref/heads/" in path:
            return _resp(200, {"object": {"sha": self._sha}})
        if "/git/trees/" in path:
            return _resp(200, {"tree": self._tree, "truncated": self._truncated})
        return _resp(404)


@pytest.mark.unit
class TestGitHubVcsAdapterListTree:
    def test_returns_blob_paths_only(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        tree = [
            {"path": "api-v2.0", "type": "tree"},
            {"path": "api-v2.0/components/x/y.py", "type": "blob"},
            {"path": "README.md", "type": "blob"},
            {"path": "sub", "type": "commit"},  # submodule — excluded
        ]
        fake = _FakeTreeGitHub(tree)
        with mock.patch(_REQUESTS_PATH, new=fake):
            paths = adapter.list_tree("acme/app", "main")
        assert paths == ["api-v2.0/components/x/y.py", "README.md"]
        # It resolved the ref → sha, then read the recursive tree.
        assert any("/git/ref/heads/main" in c for c in fake.calls)
        assert any("/git/trees/treesha" in c for c in fake.calls)
        # Invariant the resolver leans on: git trees never carry `..` segments.
        assert not any(".." in p.split("/") for p in paths)

    def test_truncated_tree_warns(self, caplog):
        adapter = GitHubVcsAdapter("ghp_secret_token")
        fake = _FakeTreeGitHub([{"path": "a.py", "type": "blob"}], truncated=True)
        with mock.patch(_REQUESTS_PATH, new=fake), caplog.at_level(logging.WARNING):
            paths = adapter.list_tree("acme/app", "main")
        assert paths == ["a.py"]
        assert any("github_tree_truncated" in r.message for r in caplog.records)

    def test_unresolvable_ref_raises(self):
        adapter = GitHubVcsAdapter("ghp_secret_token")

        def _no_sha(method, url, headers=None, json=None, params=None, timeout=None):
            if "/git/ref/heads/" in url:
                return _resp(200, {"object": {}})  # no sha
            return _resp(404)

        with mock.patch(_REQUESTS_PATH, new=_no_sha), pytest.raises(VcsApiError):
            adapter.list_tree("acme/app", "main")
