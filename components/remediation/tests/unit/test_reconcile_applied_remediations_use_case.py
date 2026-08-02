"""Unit tests for the remediation reconciler use case (ADR 0012 P4a).

Pure orchestration — the three cross-context reaches (merge check, resolve-finding,
gated capture) are injected fakes. Proves the branching contract:

- merged PR    → finding resolved AND fix offered to the gate (captured),
- unmerged PR  → nothing resolved, nothing captured,
- gate refusal → the finding is still resolved, but no entry is admitted,
- a per-item error never sinks the batch.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.remediation.application.use_cases.reconcile_applied_remediations_use_case import (
    ReconcileAppliedRemediationsUseCase,
    RemediationCandidate,
)

pytestmark = pytest.mark.unit


def _candidate(**overrides) -> RemediationCandidate:
    base = dict(
        workspace_id=uuid4(),
        finding_task_id="101",
        draft_pr_url="https://github.com/acme/app/pull/7",
        sign_off_artifact_type="remediation",
        sign_off_artifact_id="signoff-1",
        code="raw fix",
        language="python",
        title="Fix casing import",
    )
    base.update(overrides)
    return RemediationCandidate(**base)


class _Recorder:
    """Captures calls so the test can assert the reconciler did (or didn't) act."""

    def __init__(self, *, merged: bool, capture_returns):
        self._merged = merged
        self._capture_returns = capture_returns
        self.merge_checks: list[str] = []
        self.resolved: list[str] = []
        self.captured: list[str] = []

    def check_merged(self, ws_id, pr_url):
        self.merge_checks.append(pr_url)
        return self._merged

    def resolve_finding(self, ws_id, task_id, reason, resolved_by):
        self.resolved.append(task_id)
        return True

    def capture(self, **kwargs):
        self.captured.append(kwargs["finding_task_id"])
        return self._capture_returns


def _run(recorder, candidates):
    uc = ReconcileAppliedRemediationsUseCase(
        check_merged=recorder.check_merged,
        resolve_finding=recorder.resolve_finding,
        capture=recorder.capture,
    )
    return uc.execute(candidates)


class TestMergedPath:
    def test_merged_resolves_and_captures(self):
        rec = _Recorder(merged=True, capture_returns=object())  # gate admitted an entry
        result = _run(rec, [_candidate(finding_task_id="101")])
        assert rec.merge_checks == ["https://github.com/acme/app/pull/7"]
        assert rec.resolved == ["101"]  # resolved through the project surface
        assert rec.captured == ["101"]  # offered to the gate
        assert (result.scanned, result.merged, result.resolved, result.captured) == (1, 1, 1, 1)
        assert result.gate_refused == 0

    def test_gate_refusal_still_resolves_but_captures_nothing(self):
        rec = _Recorder(merged=True, capture_returns=None)  # gate refused (None)
        result = _run(rec, [_candidate(finding_task_id="55")])
        assert rec.resolved == ["55"]  # resolution and admission are separate
        assert rec.captured == ["55"]  # it WAS offered — the gate declined
        assert result.captured == 0
        assert result.gate_refused == 1


class TestUnmergedPath:
    def test_unmerged_does_nothing(self):
        rec = _Recorder(merged=False, capture_returns=object())
        result = _run(rec, [_candidate()])
        assert rec.resolved == []
        assert rec.captured == []  # never resolved, never captured
        assert (result.scanned, result.merged, result.skipped_unmerged) == (1, 0, 1)


class TestResilience:
    def test_one_bad_item_never_sinks_the_batch(self):
        good = _candidate(finding_task_id="1")
        bad = _candidate(finding_task_id="2")
        other = _candidate(finding_task_id="3")

        def check_merged(ws_id, pr_url):
            return True

        def resolve_finding(ws_id, task_id, reason, resolved_by):
            if task_id == "2":
                raise RuntimeError("resolve blew up")
            return True

        captured: list[str] = []

        def capture(**kwargs):
            captured.append(kwargs["finding_task_id"])
            return object()

        uc = ReconcileAppliedRemediationsUseCase(
            check_merged=check_merged, resolve_finding=resolve_finding, capture=capture
        )
        result = uc.execute([good, bad, other])
        assert captured == ["1", "3"]  # 2 errored but 1 and 3 still processed
        assert result.errors == 1
        assert result.captured == 2
