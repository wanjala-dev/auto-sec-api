"""The merge-check adapter delegates to the integrations VcsPort (ADR 0012 P4a).

Proves the remediation → integrations seam: with a CONNECTED VcsConnection the
adapter decrypts the token, resolves the GitHub adapter, and reads the PR's
``merged`` boolean. Fail-closed: no connection → ``checked=False`` (the reconciler
then skips, never assumes merged). The GitHub HTTP layer is stubbed — no live call.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from components.remediation.infrastructure.adapters.vcs_pull_request_merge_check_adapter import (
    VcsPullRequestMergeCheckAdapter,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_REQUESTS_PATH = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.requests.request"
_PR_URL = "https://github.com/acme/repo/pull/7"


def _resp(status_code: int, payload: dict | None = None):
    payload = payload or {}
    return SimpleNamespace(status_code=status_code, text=__import__("json").dumps(payload), json=lambda: payload)


def _connect(workspace):
    from components.integrations.application.providers.secret_envelope_provider import encrypt_secret
    from infrastructure.persistence.integrations.models import VcsConnection

    return VcsConnection.objects.create(
        workspace=workspace,
        provider=VcsConnection.Provider.GITHUB,
        repo_allowlist=["acme/repo"],
        token_ciphertext=encrypt_secret("ghp_secret_token"),
        status=VcsConnection.Status.CONNECTED,
    )


class TestMergedDelegation:
    def test_merged_pr_returns_checked_merged(self, workspace_factory):
        ws = workspace_factory()
        _connect(ws)
        payload = {"number": 7, "state": "closed", "merged": True}
        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, payload)):
            status = VcsPullRequestMergeCheckAdapter().check_merged(
                workspace_id=str(ws.id), repo="acme/repo", pr_ref=_PR_URL
            )
        assert status.checked is True
        assert status.merged is True

    def test_open_pr_returns_checked_not_merged(self, workspace_factory):
        ws = workspace_factory()
        _connect(ws)
        payload = {"number": 7, "state": "open", "merged": False}
        with mock.patch(_REQUESTS_PATH, return_value=_resp(200, payload)):
            status = VcsPullRequestMergeCheckAdapter().check_merged(
                workspace_id=str(ws.id), repo="acme/repo", pr_ref=_PR_URL
            )
        assert status.checked is True
        assert status.merged is False


class TestFailClosed:
    def test_no_connection_is_unchecked(self, workspace_factory):
        ws = workspace_factory()  # no VcsConnection
        status = VcsPullRequestMergeCheckAdapter().check_merged(
            workspace_id=str(ws.id), repo="acme/repo", pr_ref=_PR_URL
        )
        assert status.checked is False
        assert status.merged is False

    def test_api_error_is_unchecked_not_merged(self, workspace_factory):
        ws = workspace_factory()
        _connect(ws)
        with mock.patch(_REQUESTS_PATH, return_value=_resp(404, {"message": "Not Found"})):
            status = VcsPullRequestMergeCheckAdapter().check_merged(
                workspace_id=str(ws.id), repo="acme/repo", pr_ref=_PR_URL
            )
        # A read failure is "could not verify", NEVER "not merged as fact".
        assert status.checked is False
        assert status.merged is False
