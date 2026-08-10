"""Unit tests: the legacy draft-PR patch backfill (no DB, no network).

Every collaborator is an in-memory fake, so these pin the use case's judgement —
what it fills, what it refuses to fill, and what it never invents:

* a patch-less record is filled from the host's PR patch;
* a record that already has a diff never even reaches the host;
* a closed/merged PR is filled ANYWAY, carrying its lifecycle state;
* a 404 / unreadable PR, a de-allowlisted repo, a patch-less response and a
  missing connection each SKIP with a named reason — never a fabricated diff;
* ``--dry-run`` reads but writes nothing.
"""

from __future__ import annotations

import pytest

from components.integrations.application.ports.finding_facts_port import DraftPrPatchGap
from components.integrations.application.ports.vcs_port import (
    PullRequestPatch,
    PullRequestState,
    VcsApiError,
)
from components.integrations.application.use_cases.backfill_draft_pr_patches_use_case import (
    BackfillDraftPrPatchesUseCase,
)

_WS = "cc287133-b53c-43c8-9000-2873f8c8a1e3"
_PR_URL = "https://github.com/wanjala-dev/api-v0.2.0/pull/867"
_REPO = "wanjala-dev/api-v0.2.0"
_PATH = "components/identity/infrastructure/adapters/apple_auth.py"
_DIFF = f"--- a/{_PATH}\n+++ b/{_PATH}\n@@ -37,7 +37,7 @@\n-    unsafe\n+    safe\n"


class _FakeFacts:
    def __init__(self, gaps):
        self._gaps = tuple(gaps)
        self.calls = []

    def list_draft_pr_patch_gaps(self, *, workspace_id="", limit=500):
        self.calls.append((workspace_id, limit))
        return self._gaps


class _FakeRecorder:
    def __init__(self, *, attached=True, reason="attached"):
        self._attached = attached
        self._reason = reason
        self.writes = []

    def attach_draft_pr_patch(self, **kwargs):
        self.writes.append(kwargs)
        return self._attached, self._reason


class _FakeAdapter:
    def __init__(self, *, patch=None, state=None, error=None):
        self._patch = patch or PullRequestPatch(path=_PATH, diff=_DIFF, file_count=1)
        self._state = state or PullRequestState(merged=False, state="open")
        self._error = error
        self.reads = []

    def get_pull_request_patch(self, repo, pr_ref):
        self.reads.append((repo, pr_ref))
        if self._error:
            raise self._error
        return self._patch

    def get_pull_request(self, repo, pr_ref):
        if self._error:
            raise self._error
        return self._state


class _Connection:
    def __init__(self, *, allowlist=(_REPO,), token="ghp_secret", provider="github"):
        self.repo_allowlist = list(allowlist)
        self.token_ciphertext = "cipher" if token else ""
        self.provider = provider


def _gap(task_id="9846"):
    return DraftPrPatchGap(workspace_id=_WS, task_id=task_id, pr_url=_PR_URL, repo=_REPO)


def _build(*, gaps=None, adapter=None, connection=..., recorder=None):
    facts = _FakeFacts(gaps if gaps is not None else [_gap()])
    recorder = recorder or _FakeRecorder()
    adapter = adapter if adapter is not None else _FakeAdapter()
    connection = _Connection() if connection is ... else connection
    use_case = BackfillDraftPrPatchesUseCase(
        finding_facts=facts,
        pr_recorder=recorder,
        resolve_connection=lambda _ws: connection,
        decrypt=lambda cipher: "ghp_secret" if cipher else "",
        resolve_adapter=lambda _provider, _token: adapter,
    )
    return use_case, facts, recorder, adapter


@pytest.mark.unit
class TestBackfillDraftPrPatches:
    def test_fills_a_legacy_record_from_the_hosts_patch(self):
        use_case, _facts, recorder, adapter = _build()

        report = use_case.execute()

        assert report.filled == 1
        assert report.skipped == 0
        assert adapter.reads == [(_REPO, 867)]
        write = recorder.writes[0]
        assert write["task_id"] == "9846"
        assert write["path"] == _PATH
        assert write["diff"] == _DIFF
        assert write["reason"] == "legacy_patch_backfill"

    def test_never_invents_a_change_summary(self):
        use_case, _facts, recorder, _adapter = _build()

        use_case.execute()

        # Legacy records predate the advisor summary and it is not recoverable —
        # the record says nothing rather than something plausible.
        assert recorder.writes[0]["change_summary"] == ""

    def test_fills_a_merged_pr_and_records_its_state(self):
        adapter = _FakeAdapter(state=PullRequestState(merged=True, state="closed", merged_at="2026-07-30T00:00:00Z"))
        use_case, _facts, recorder, _ = _build(adapter=adapter)

        report = use_case.execute()

        assert report.filled == 1
        write = recorder.writes[0]
        assert write["diff"] == _DIFF  # a merged PR still carried a patch
        assert write["pr_state"] == "closed"
        assert write["merged"] is True
        assert report.outcomes[0].merged is True

    def test_skips_an_unreachable_pr_without_writing(self):
        adapter = _FakeAdapter(error=VcsApiError("gone", status_code=404))
        use_case, _facts, recorder, _ = _build(adapter=adapter)

        report = use_case.execute()

        assert report.filled == 0
        assert report.skipped == 1
        assert report.outcomes[0].reason == "host_api_error_404"
        assert recorder.writes == []

    def test_skips_a_permission_denied_pr_without_writing(self):
        adapter = _FakeAdapter(error=VcsApiError("forbidden", status_code=403))
        use_case, _facts, recorder, _ = _build(adapter=adapter)

        report = use_case.execute()

        assert report.outcomes[0].reason == "host_api_error_403"
        assert recorder.writes == []

    def test_skips_a_repo_the_operator_never_allowlisted(self):
        use_case, _facts, recorder, adapter = _build(connection=_Connection(allowlist=("someone/else",)))

        report = use_case.execute()

        assert report.outcomes[0].reason == "repo_not_allowlisted"
        assert adapter.reads == []  # the consent gate fires BEFORE any host call
        assert recorder.writes == []

    def test_skips_when_the_host_returns_no_reviewable_patch(self):
        adapter = _FakeAdapter(patch=PullRequestPatch(path="x.bin", diff="", file_count=1))
        use_case, _facts, recorder, _ = _build(adapter=adapter)

        report = use_case.execute()

        assert report.outcomes[0].reason == "no_patch_returned"
        assert recorder.writes == []

    def test_skips_a_workspace_with_no_vcs_connection(self):
        use_case, _facts, recorder, adapter = _build(connection=None)

        report = use_case.execute()

        assert report.outcomes[0].reason == "no_usable_vcs_connection"
        assert adapter.reads == []
        assert recorder.writes == []

    def test_skips_an_unparseable_pr_url(self):
        gap = DraftPrPatchGap(workspace_id=_WS, task_id="1", pr_url="https://example.com/not-a-pr", repo=_REPO)
        use_case, _facts, recorder, adapter = _build(gaps=[gap])

        report = use_case.execute()

        assert report.outcomes[0].reason == "unparseable_pr_url"
        assert adapter.reads == []
        assert recorder.writes == []

    def test_dry_run_reads_but_writes_nothing(self):
        use_case, _facts, recorder, adapter = _build()

        report = use_case.execute(dry_run=True)

        assert recorder.writes == []
        assert adapter.reads == [(_REPO, 867)]
        assert report.outcomes[0].reason == "dry_run"
        assert report.outcomes[0].diff_chars == len(_DIFF)

    def test_reports_the_owning_writes_idempotent_skip(self):
        # A record that gained a diff between the sweep and the write (or a re-run
        # racing itself) is reported as skipped, not filled.
        recorder = _FakeRecorder(attached=False, reason="already_has_diff")
        use_case, _facts, _recorder, _adapter = _build(recorder=recorder)

        report = use_case.execute()

        assert report.filled == 0
        assert report.skipped == 1
        assert report.outcomes[0].reason == "already_has_diff"

    def test_scopes_the_sweep_and_limit_it_is_given(self):
        use_case, facts, _recorder, _adapter = _build()

        use_case.execute(workspace_id=_WS, limit=25)

        assert facts.calls == [(_WS, 25)]

    def test_resolves_the_connection_once_per_workspace(self):
        calls = []

        def _resolve(workspace_id):
            calls.append(workspace_id)
            return _Connection()

        use_case = BackfillDraftPrPatchesUseCase(
            finding_facts=_FakeFacts([_gap("1"), _gap("2"), _gap("3")]),
            pr_recorder=_FakeRecorder(),
            resolve_connection=_resolve,
            decrypt=lambda _c: "ghp_secret",
            resolve_adapter=lambda _p, _t: _FakeAdapter(),
        )
        report = use_case.execute()

        assert report.filled == 3
        assert calls == [_WS]  # memoised — one connection read + decrypt for the sweep
