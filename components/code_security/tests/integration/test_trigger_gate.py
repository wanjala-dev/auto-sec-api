"""Integration: the trigger-time consent gate (ADR 0019 D2 — allowlist fail-closed)."""

from __future__ import annotations

import pytest

from components.code_security.application.use_cases.trigger_repo_scan_use_case import (
    RepoScanRejected,
    TriggerRepoScanUseCase,
)
from components.integrations.application.providers.vcs_scan_access_provider import (
    list_scannable_repos,
    resolve_scan_connection,
)
from infrastructure.persistence.integrations.models import VcsConnection

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_REPO = "wanjala-dev/auto-sec-api"


def _connection(ws, *, allowlist, status=VcsConnection.Status.CONNECTED):
    return VcsConnection.objects.create(
        workspace=ws,
        provider=VcsConnection.Provider.GITHUB,
        name="GitHub",
        repo_allowlist=allowlist,
        status=status,
    )


def test_prepare_passes_for_an_allowlisted_repo(workspace_factory):
    ws = workspace_factory()
    connection = _connection(ws, allowlist=[_REPO])

    kwargs = TriggerRepoScanUseCase().prepare(workspace_id=ws.id, repo=_REPO)
    assert kwargs["source"] == "code_security.opengrep"
    assert kwargs["target_ref"] == _REPO
    assert kwargs["connection_id"] == str(connection.id)


def test_prepare_rejects_a_repo_not_on_the_allowlist(workspace_factory):
    ws = workspace_factory()
    _connection(ws, allowlist=["other/repo"])

    with pytest.raises(RepoScanRejected) as excinfo:
        TriggerRepoScanUseCase().prepare(workspace_id=ws.id, repo=_REPO)
    assert excinfo.value.code == "repo_not_allowlisted"


def test_prepare_rejects_a_malformed_repo_reference(workspace_factory):
    ws = workspace_factory()
    _connection(ws, allowlist=[_REPO])

    with pytest.raises(RepoScanRejected) as excinfo:
        TriggerRepoScanUseCase().prepare(workspace_id=ws.id, repo="owner/repo; rm -rf /")
    assert excinfo.value.code == "invalid_repo"


def test_resolve_ignores_another_workspaces_connection(workspace_factory):
    ws_a = workspace_factory()
    ws_b = workspace_factory()
    _connection(ws_a, allowlist=[_REPO])

    assert resolve_scan_connection(ws_b.id, _REPO) is None


def test_list_scannable_repos_skips_disconnected_and_dedupes(workspace_factory):
    ws = workspace_factory()
    newest = _connection(ws, allowlist=["a/one", "a/two"])
    _connection(ws, allowlist=["a/dead"], status=VcsConnection.Status.ERROR)

    targets = dict(list_scannable_repos(ws.id))
    assert set(targets) == {"a/one", "a/two"}
    assert targets["a/one"] == str(newest.id)
