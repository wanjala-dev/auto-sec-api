"""Unit tests for the P4a reconciler use case — pure orchestration, no DB.

Fakes stand in for every port so the merge → resolve → capture choreography is
exercised in isolation: a verified merge resolves the finding and offers the fix
to the gate; an unverified/unmerged PR changes nothing; the capture callable is
invoked with a VERIFIED ``pr_applied=True`` only for a confirmed merge.
"""

from __future__ import annotations

import pytest

from components.remediation.application.ports.open_draft_pr_findings_port import (
    OpenDraftPrFinding,
    OpenDraftPrFindingsPort,
)
from components.remediation.application.ports.pull_request_merge_check_port import (
    MergeStatus,
    PullRequestMergeCheckPort,
)
from components.remediation.application.use_cases.reconcile_merged_remediations_use_case import (
    ReconcileMergedRemediationsUseCase,
)
from components.remediation.tests.unit.fakes import FakeFindingFacts, make_facts

pytestmark = pytest.mark.unit

_WS = "11111111-1111-1111-1111-111111111111"


class _FakeCandidates(OpenDraftPrFindingsPort):
    def __init__(self, items):
        self._items = items

    def iter_open_draft_pr_findings(self, *, chunk_size: int = 500):
        yield from self._items


class _FakeMergeCheck(PullRequestMergeCheckPort):
    def __init__(self, status: MergeStatus):
        self._status = status
        self.calls: list[tuple] = []

    def check_merged(self, *, workspace_id: str, repo: str, pr_ref: str) -> MergeStatus:
        self.calls.append((workspace_id, repo, pr_ref))
        return self._status


class _FakeResolution:
    def __init__(self):
        self.resolved: list[tuple] = []

    def mark_resolved(self, *, workspace_id: str, finding_task_id: str, reason: str) -> bool:
        self.resolved.append((workspace_id, finding_task_id, reason))
        return True


class _RecordingCapture:
    def __init__(self, *, returns=object()):
        self._returns = returns
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._returns


def _candidate(task_id="55"):
    return OpenDraftPrFinding(
        workspace_id=_WS,
        finding_task_id=task_id,
        repo="acme/repo",
        pr_url="https://github.com/acme/repo/pull/7",
    )


def _build(*, merge_status, facts, resolution, capture):
    return ReconcileMergedRemediationsUseCase(
        candidates=_FakeCandidates([_candidate()]),
        merge_check=_FakeMergeCheck(merge_status),
        finding_facts=FakeFindingFacts(facts),
        resolution=resolution,
        capture=capture,
    )


class TestMergedPath:
    def test_merged_resolves_finding_and_offers_capture(self):
        resolution = _FakeResolution()
        capture = _RecordingCapture(returns=object())  # gate admits → non-None
        uc = _build(
            merge_status=MergeStatus(checked=True, merged=True, pr_url="pr"),
            facts=make_facts(finding_task_id="55", workspace_id=_WS, fix_code="fix()"),
            resolution=resolution,
            capture=capture,
        )

        result = uc.execute()

        assert result.merged == 1
        assert result.resolved == 1
        assert result.captured == 1
        assert len(resolution.resolved) == 1  # finding was resolved
        # Capture was called with VERIFIED applied=True.
        assert capture.calls[0]["pr_applied"] is True
        assert capture.calls[0]["applied_pr_url"] == make_facts().draft_pr_url
        assert capture.calls[0]["code"] == "fix()"

    def test_merged_but_gate_refuses_resolves_without_capture(self):
        # sign_off NOT approved → capture facade returns None (gate refused). The
        # finding still resolves; no corpus entry is recorded.
        resolution = _FakeResolution()
        capture = _RecordingCapture(returns=None)
        uc = _build(
            merge_status=MergeStatus(checked=True, merged=True, pr_url="pr"),
            facts=make_facts(finding_task_id="55", workspace_id=_WS, fix_code="fix()"),
            resolution=resolution,
            capture=capture,
        )

        result = uc.execute()

        assert result.resolved == 1
        assert result.captured == 0
        assert len(resolution.resolved) == 1
        assert len(capture.calls) == 1  # it was offered; the gate said no

    def test_merged_with_no_fix_code_resolves_without_capture(self):
        resolution = _FakeResolution()
        capture = _RecordingCapture()
        uc = _build(
            merge_status=MergeStatus(checked=True, merged=True, pr_url="pr"),
            facts=make_facts(finding_task_id="55", workspace_id=_WS, fix_code=""),
            resolution=resolution,
            capture=capture,
        )

        result = uc.execute()

        assert result.resolved == 1
        assert result.captured == 0
        assert capture.calls == []  # nothing groundable → never offered


class TestUnmergedPath:
    def test_not_merged_changes_nothing(self):
        resolution = _FakeResolution()
        capture = _RecordingCapture()
        uc = _build(
            merge_status=MergeStatus(checked=True, merged=False),
            facts=make_facts(finding_task_id="55", workspace_id=_WS),
            resolution=resolution,
            capture=capture,
        )

        result = uc.execute()

        assert result.merged == 0
        assert result.resolved == 0
        assert result.captured == 0
        assert resolution.resolved == []
        assert capture.calls == []

    def test_unverifiable_merge_changes_nothing(self):
        # checked=False (no connection / API error) is NOT treated as merged.
        resolution = _FakeResolution()
        capture = _RecordingCapture()
        uc = _build(
            merge_status=MergeStatus(checked=False, merged=False, detail="no connection"),
            facts=make_facts(finding_task_id="55", workspace_id=_WS),
            resolution=resolution,
            capture=capture,
        )

        result = uc.execute()

        assert result.resolved == 0
        assert resolution.resolved == []
        assert capture.calls == []


class TestResilience:
    def test_one_failing_item_does_not_abort_the_sweep(self):
        good = _candidate("55")
        bad = OpenDraftPrFinding(workspace_id="not-a-uuid", finding_task_id="66", repo="x/y", pr_url="u")

        class _Candidates(OpenDraftPrFindingsPort):
            def iter_open_draft_pr_findings(self, *, chunk_size: int = 500):
                yield bad
                yield good

        resolution = _FakeResolution()
        capture = _RecordingCapture(returns=object())
        uc = ReconcileMergedRemediationsUseCase(
            candidates=_Candidates(),
            merge_check=_FakeMergeCheck(MergeStatus(checked=True, merged=True, pr_url="pr")),
            finding_facts=FakeFindingFacts(make_facts(finding_task_id="55", workspace_id=_WS, fix_code="fix()")),
            resolution=resolution,
            capture=capture,
        )

        result = uc.execute()

        # Both scanned; the bad one raised inside _reconcile_one (UUID("not-a-uuid"))
        # and was skipped; the good one still processed.
        assert result.scanned == 2
        assert result.captured == 1
