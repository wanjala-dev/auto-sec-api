"""Unit tests for the PR-merge check surface (ADR 0012 P4a).

Pure orchestration — no DB, no HTTP. A scripted adapter returns a
``PullRequestState``; a fake connection carries the allowlist + token ciphertext.
Proves URL parsing, the allowlist consent boundary, fail-closed behaviour on every
expected failure, and that a merged PR is reported merged.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from components.integrations.application.ports.vcs_port import PullRequestState, VcsApiError
from components.integrations.application.use_cases.check_pull_request_merged_use_case import (
    CheckPullRequestMergedUseCase,
    parse_pr_url,
)

pytestmark = pytest.mark.unit

_URL = "https://github.com/acme/app/pull/7"


class _FakeAdapter:
    def __init__(self, state: PullRequestState | None = None, *, raises: VcsApiError | None = None):
        self._state = state
        self._raises = raises
        self.calls: list[tuple[str, object]] = []

    def get_pull_request(self, repo, pr_ref):
        self.calls.append((repo, pr_ref))
        if self._raises:
            raise self._raises
        return self._state


def _connection(*, allowlist=("acme/app",), token_ciphertext="ct", provider="github"):
    return SimpleNamespace(repo_allowlist=list(allowlist), token_ciphertext=token_ciphertext, provider=provider)


def _use_case(*, connection=..., adapter=None, decrypt=lambda ct: "tok"):
    conn = _connection() if connection is ... else connection
    adapter = adapter or _FakeAdapter(PullRequestState(merged=True, state="closed", merged_at="t"))
    return CheckPullRequestMergedUseCase(
        resolve_connection=lambda ws: conn,
        decrypt=decrypt,
        resolve_adapter=lambda provider, token: adapter,
    )


class TestParsePrUrl:
    def test_github_pull_url(self):
        assert parse_pr_url("https://github.com/acme/app/pull/42") == ("acme/app", 42)

    def test_gitlab_merge_request_url(self):
        assert parse_pr_url("https://gitlab.com/acme/app/merge_requests/9") == ("acme/app", 9)

    def test_trailing_slash_and_query(self):
        assert parse_pr_url("https://github.com/a/b/pull/3/files?x=1") == ("a/b", 3)

    def test_garbage_returns_none(self):
        assert parse_pr_url("not a url") is None
        assert parse_pr_url("") is None


class TestMergeCheck:
    def test_merged_pr_is_merged(self):
        adapter = _FakeAdapter(PullRequestState(merged=True, state="closed", merged_at="t"))
        status = _use_case(adapter=adapter).execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is True
        assert status.allowed is True
        assert adapter.calls == [("acme/app", 7)]

    def test_open_pr_is_not_merged(self):
        adapter = _FakeAdapter(PullRequestState(merged=False, state="open"))
        status = _use_case(adapter=adapter).execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is False
        assert status.allowed is True

    def test_unparseable_url_fails_closed(self):
        status = _use_case().execute(workspace_id="ws", pr_url="junk")
        assert status.merged is False and status.allowed is False
        assert status.reason == "unparseable_pr_url"

    def test_no_connection_fails_closed(self):
        status = _use_case(connection=None).execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is False and status.allowed is False
        assert status.reason == "no_vcs_connection"

    def test_repo_not_allowlisted_refused(self):
        # A URL pointing at a repo the operator never allowlisted is refused BEFORE
        # any host call — a spoofed URL can never drive a corpus write.
        adapter = _FakeAdapter(PullRequestState(merged=True, state="closed"))
        uc = _use_case(connection=_connection(allowlist=("other/repo",)), adapter=adapter)
        status = uc.execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is False and status.allowed is False
        assert status.reason == "repo_not_allowlisted"
        assert adapter.calls == []  # never called the host

    def test_no_token_fails_closed(self):
        status = _use_case(decrypt=lambda ct: "").execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is False and status.allowed is False
        assert status.reason == "no_token"

    def test_host_api_error_fails_closed_but_allowed(self):
        adapter = _FakeAdapter(raises=VcsApiError("boom", status_code=500))
        status = _use_case(adapter=adapter).execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is False
        assert status.allowed is True  # the URL WAS allowlisted; the host just failed
        assert status.reason == "host_api_error"


class TestAuthStrategy:
    """Phase B: the per-connection resolve_token seam, when wired, is authoritative."""

    def test_resolve_token_is_preferred_over_decrypt(self):
        adapter = _FakeAdapter(PullRequestState(merged=True, state="closed", merged_at="t"))
        uc = CheckPullRequestMergedUseCase(
            resolve_connection=lambda ws: _connection(),
            decrypt=lambda ct: (_ for _ in ()).throw(AssertionError("raw decrypt used despite strategy")),
            resolve_adapter=lambda provider, token: adapter,
            resolve_token=lambda conn: "ghs_app_token",
        )
        status = uc.execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is True

    def test_revoked_installation_fails_closed(self):
        # A typed app-auth failure (revoked/suspended installation) means the
        # merge cannot be confirmed — skip, never crash the reconciler.
        adapter = _FakeAdapter(PullRequestState(merged=True, state="closed"))
        uc = CheckPullRequestMergedUseCase(
            resolve_connection=lambda ws: _connection(),
            decrypt=lambda ct: "tok",
            resolve_adapter=lambda provider, token: adapter,
            resolve_token=lambda conn: (_ for _ in ()).throw(VcsApiError("revoked", status_code=404)),
        )
        status = uc.execute(workspace_id="ws", pr_url=_URL)
        assert status.merged is False and status.allowed is False
        assert status.reason == "token_unavailable"
        assert adapter.calls == []  # the host was never reached
