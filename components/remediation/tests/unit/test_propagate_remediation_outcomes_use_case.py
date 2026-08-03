"""Unit tests — outcome propagation (ADR 0012 P5): a new admission scores its priors.

Proves the classification at the capture seam:
- a same-``finding_kind`` prior with a DIFFERENT fingerprint gets reuse+success
  (its score rises) — it grounded a same-class fix that landed;
- a prior with the SAME fingerprint gets recurrence (its score falls) — the exact
  finding came back, so that fix did not hold;
- each mutated prior is re-embedded so retrieval ranks on the new rating;
- writes go through the store (which derives the score) — never a raw score set.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.remediation.application.use_cases.propagate_remediation_outcomes_use_case import (
    PropagateRemediationOutcomesUseCase,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.domain.services.remediation_ranking_policy import (
    RemediationRankingPolicy,
)
from components.remediation.tests.unit.fakes import FakeStore

pytestmark = pytest.mark.unit

_WS = uuid4()


def _entry(*, finding_kind="log_watch", fingerprint="fp", task="t", workspace_id=_WS):
    return RemediationEntry(
        id=uuid4(),
        workspace_id=workspace_id,
        finding_kind=finding_kind,
        source_type="ai." + finding_kind,
        tags=(),
        language="python",
        code="fix()",
        title="Fix",
        summary="",
        finding_task_id=task,
        finding_fingerprint=fingerprint,
        provenance_event_ref="agent:triage@t1",
        applied_pr_url="https://github.com/acme/repo/pull/1",
        approved_by="signoff-1",
        resolved_at=datetime.now(UTC),
        score=RemediationRankingPolicy.derive_score(reuse_count=0, success_count=0, recurrence_count=0),
    )


class TestOutcomePropagation:
    def test_same_kind_different_fingerprint_is_reuse_success(self):
        store = FakeStore()
        prior = _entry(fingerprint="fp-A", task="t-A")
        store.save(prior)
        reembedded: list = []
        uc = PropagateRemediationOutcomesUseCase(store=store, reembed=lambda eid, ws: reembedded.append(eid))

        new = _entry(fingerprint="fp-B", task="t-B")
        result = uc.execute(new)

        assert result.reuse_success == 1
        assert result.recurrence == 0
        bumped = store.get(prior.id, workspace_id=_WS)
        assert bumped.reuse_count == 1
        assert bumped.success_count == 1
        assert bumped.score > prior.score  # rating rose
        assert reembedded == [prior.id]  # re-embed fired so retrieval ranks on it

    def test_same_fingerprint_is_recurrence(self):
        store = FakeStore()
        prior = _entry(fingerprint="fp-SAME", task="t-old")
        store.save(prior)
        uc = PropagateRemediationOutcomesUseCase(store=store, reembed=lambda *a: None)

        # A NEW finding instance (new task id) with the SAME fingerprint = recurrence.
        new = _entry(fingerprint="fp-SAME", task="t-new")
        result = uc.execute(new)

        assert result.recurrence == 1
        assert result.reuse_success == 0
        bumped = store.get(prior.id, workspace_id=_WS)
        assert bumped.recurrence_count == 1
        assert bumped.score < prior.score  # rating fell

    def test_only_same_workspace_and_kind_priors_are_touched(self):
        store = FakeStore()
        other_kind = _entry(finding_kind="cloud_exposure", fingerprint="x", task="t1")
        other_ws = _entry(workspace_id=uuid4(), fingerprint="y", task="t2")
        same = _entry(fingerprint="z", task="t3")
        for e in (other_kind, other_ws, same):
            store.save(e)
        uc = PropagateRemediationOutcomesUseCase(store=store, reembed=lambda *a: None)

        result = uc.execute(_entry(fingerprint="new", task="t4"))

        assert result.reuse_success == 1  # only `same` (same ws + kind, diff fp)
        assert store.get(other_kind.id, workspace_id=other_kind.workspace_id).reuse_count == 0
        assert store.get(other_ws.id, workspace_id=other_ws.workspace_id).reuse_count == 0

    def test_no_priors_is_a_noop(self):
        store = FakeStore()
        uc = PropagateRemediationOutcomesUseCase(store=store, reembed=lambda *a: None)
        result = uc.execute(_entry())
        assert result.reuse_success == 0 and result.recurrence == 0
