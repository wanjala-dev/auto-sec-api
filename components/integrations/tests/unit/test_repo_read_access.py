"""Repo reads for the SAST specialist — consent-scoped, fail-closed (ADR 0025 P2).

The specialist could triage a finding but not read the project it was fixing. Its
tools ranked repos and listed findings; none could answer "where does this codebase
get its signing key?". Asked to verify a JWT signature it invented `fetch_jwks_key`
(PR #326) — a tool-inventory failure no prompt wording can fix, because no wording
makes a model know a file it cannot open.

These reads widen what the agent can see, so the tests that matter most are the
NEGATIVE ones: a repo the workspace never consented to must stay unreachable, and
every failure must degrade to an empty result rather than ending a triage run.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.ports.vcs_port import RepoCodeHit, VcsApiError
from components.integrations.infrastructure.adapters import vcs_scan_access as access

pytestmark = pytest.mark.unit

_WS = "11111111-1111-1111-1111-111111111111"
_REPO = "wanjala-dev/auto-sec-api"
_MOD = "components.integrations.infrastructure.adapters.vcs_scan_access"


class _Adapter:
    def __init__(self, *, tree=None, hits=None, raises=False):
        self._tree = tree or []
        self._hits = hits or []
        self._raises = raises
        self.searched: list[tuple] = []

    def get_default_branch(self, repo):
        return mock.Mock(name="main")

    def list_tree(self, repo, ref):
        if self._raises:
            raise VcsApiError("boom")
        return list(self._tree)

    def search_code(self, repo, query, *, limit=20):
        if self._raises:
            raise VcsApiError("no code search here")
        self.searched.append((repo, query, limit))
        return list(self._hits)


class TestConsentIsTheOnlyWayIn:
    """A repo off the allowlist must never reach the VCS API."""

    @mock.patch(f"{_MOD}.resolve_scan_connection", return_value=None)
    def test_tree_read_on_an_unconsented_repo_returns_empty(self, _resolve):
        assert access.list_repo_tree(workspace_id=_WS, repo="attacker/private", ref="main") == []

    @mock.patch(f"{_MOD}.resolve_scan_connection", return_value=None)
    def test_search_on_an_unconsented_repo_returns_empty(self, _resolve):
        assert access.search_repo(workspace_id=_WS, repo="attacker/private", query="password") == []

    @mock.patch(f"{_MOD}._consented_adapter", return_value=(None, None))
    def test_no_adapter_means_no_call(self, _consent):
        assert access.search_repo(workspace_id=_WS, repo=_REPO, query="jwt") == []
        assert access.list_repo_tree(workspace_id=_WS, repo=_REPO) == []


class TestFailuresDegradeNeverRaise:
    """A triage run must not die because a read failed."""

    def test_search_survives_a_provider_without_code_search(self):
        with mock.patch(f"{_MOD}._consented_adapter", return_value=(_Adapter(raises=True), object())):
            assert access.search_repo(workspace_id=_WS, repo=_REPO, query="jwt") == []

    def test_tree_survives_an_api_error(self):
        with mock.patch(f"{_MOD}._consented_adapter", return_value=(_Adapter(raises=True), object())):
            assert access.list_repo_tree(workspace_id=_WS, repo=_REPO) == []

    def test_an_empty_query_never_reaches_the_api(self):
        adapter = _Adapter(hits=[RepoCodeHit(path="a.py", line_number=1, line="x")])
        with mock.patch(f"{_MOD}._consented_adapter", return_value=(adapter, object())):
            assert access.search_repo(workspace_id=_WS, repo=_REPO, query="   ") == []
        assert adapter.searched == []


class TestResultsAreUsable:
    def test_search_returns_plain_dicts_for_the_llm_tool(self):
        hits = [RepoCodeHit(path="components/identity/keys.py", line_number=12, line="JWKS_URL = ...")]
        with mock.patch(f"{_MOD}._consented_adapter", return_value=(_Adapter(hits=hits), object())):
            out = access.search_repo(workspace_id=_WS, repo=_REPO, query="JWKS")
        assert out == [{"path": "components/identity/keys.py", "line_number": 12, "line": "JWKS_URL = ..."}]

    def test_the_tree_is_capped_so_it_cannot_evict_the_finding_from_context(self):
        adapter = _Adapter(tree=[f"f{i}.py" for i in range(1000)])
        with mock.patch(f"{_MOD}._consented_adapter", return_value=(adapter, object())):
            paths = access.list_repo_tree(workspace_id=_WS, repo=_REPO, limit=25)
        assert len(paths) == 25


class TestGitHubSearchIsPinnedToOneRepo:
    """The `repo:` qualifier is ours, not the caller's — a crafted query must not
    be able to widen the search past the consented repo."""

    def test_the_repo_qualifier_is_prepended_by_the_adapter(self):
        from components.integrations.infrastructure.adapters.vcs.github_vcs_adapter import GitHubVcsAdapter

        adapter = GitHubVcsAdapter.__new__(GitHubVcsAdapter)
        with mock.patch.object(GitHubVcsAdapter, "_request", return_value={"items": []}) as req:
            adapter.search_code(_REPO, "org:evil password", limit=5)
        params = req.call_args.kwargs["params"]
        assert params["q"].startswith(f"repo:{_REPO} ")

    def test_a_positionless_match_keeps_its_path(self):
        """Knowing the file is most of the value; dropping it would be worse."""
        from components.integrations.infrastructure.adapters.vcs.github_vcs_adapter import GitHubVcsAdapter

        adapter = GitHubVcsAdapter.__new__(GitHubVcsAdapter)
        with mock.patch.object(GitHubVcsAdapter, "_request", return_value={"items": [{"path": "a/b.py"}]}):
            hits = adapter.search_code(_REPO, "jwt")
        assert hits == [RepoCodeHit(path="a/b.py", line_number=0, line="")]
