"""The gate use case: sole-writer + defense-in-depth re-checking of all three.

These tests never touch a DB — they wire the use case against in-memory fakes and
assert *what it wrote* (nothing, on any refusal). The gate must refuse when any
one condition is missing, and must not trust the caller's ``pr_applied`` claim
without a real opened draft PR whose URL matches.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.remediation.application.commands.record_remediation_entry_command import (
    RecordRemediationEntryCommand,
)
from components.remediation.application.use_cases.record_remediation_entry_use_case import (
    RecordRemediationEntryUseCase,
)
from components.remediation.domain.errors import EntryGateNotSatisfiedError
from components.remediation.domain.value_objects.gate_conditions import (
    REASON_NOT_APPLIED,
    REASON_NOT_APPROVED,
    REASON_NOT_RESOLVED,
)
from components.remediation.tests.unit.fakes import (
    FakeFindingFacts,
    FakeSignOffGate,
    FakeStore,
    make_facts,
)

pytestmark = pytest.mark.unit

_WS = uuid4()
_PR_URL = "https://github.com/acme/repo/pull/7"


def _command(**overrides):
    base = dict(
        workspace_id=_WS,
        finding_task_id="task-1",
        sign_off_artifact_type="remediation",
        sign_off_artifact_id="signoff-1",
        pr_applied=True,
        applied_pr_url=_PR_URL,
        code="- old = AiEmbeddingsProvider\n+ old = AIEmbeddingsProvider  # alias",
        language="python",
        title="Fix casing import",
    )
    base.update(overrides)
    return RecordRemediationEntryCommand(**base)


def _use_case(*, approved=True, facts=None, store=None):
    store = store or FakeStore()
    return (
        RecordRemediationEntryUseCase(
            store=store,
            sign_off_gate=FakeSignOffGate(approved=approved),
            finding_facts=FakeFindingFacts(facts or make_facts(draft_pr_url=_PR_URL)),
        ),
        store,
    )


class TestGateAdmits:
    def test_all_three_conditions_met_creates_entry(self):
        uc, store = _use_case()
        entry = uc.execute(_command())
        assert len(store.saved) == 1
        assert entry.finding_kind == "log_watch"
        assert entry.applied_pr_url == _PR_URL

    def test_idempotent_second_call_returns_same_entry_no_duplicate(self):
        uc, store = _use_case()
        first = uc.execute(_command())
        second = uc.execute(_command())
        assert first.id == second.id
        assert len(store.saved) == 1  # not written twice


class TestGateRefuses:
    def test_approved_but_not_applied_refuses(self):
        # PR was opened but the operator did NOT confirm it applied (merged).
        uc, store = _use_case()
        with pytest.raises(EntryGateNotSatisfiedError) as exc:
            uc.execute(_command(pr_applied=False))
        assert REASON_NOT_APPLIED in exc.value.unmet
        assert store.saved == []

    def test_applied_but_not_resolved_refuses(self):
        uc, store = _use_case(facts=make_facts(finding_resolved=False, draft_pr_url=_PR_URL))
        with pytest.raises(EntryGateNotSatisfiedError) as exc:
            uc.execute(_command())
        assert REASON_NOT_RESOLVED in exc.value.unmet
        assert store.saved == []

    def test_resolved_and_applied_but_not_approved_refuses(self):
        uc, store = _use_case(approved=False)
        with pytest.raises(EntryGateNotSatisfiedError) as exc:
            uc.execute(_command())
        assert REASON_NOT_APPROVED in exc.value.unmet
        assert store.saved == []

    def test_pr_applied_claimed_but_no_draft_pr_on_finding_refuses(self):
        # Caller asserts applied=True, but the finding has NO opened draft PR —
        # the gate refuses to infer "applied" from a bare claim (merge-detection
        # gap). This is the anti-poisoning teeth: you cannot assert your way in.
        uc, store = _use_case(facts=make_facts(draft_pr_url=None))
        with pytest.raises(EntryGateNotSatisfiedError) as exc:
            uc.execute(_command(pr_applied=True))
        assert REASON_NOT_APPLIED in exc.value.unmet
        assert store.saved == []

    def test_applied_url_mismatch_refuses(self):
        # The confirmed applied URL must match the finding's opened draft PR.
        uc, store = _use_case(facts=make_facts(draft_pr_url="https://github.com/acme/repo/pull/999"))
        with pytest.raises(EntryGateNotSatisfiedError):
            uc.execute(_command(applied_pr_url=_PR_URL))
        assert store.saved == []

    def test_unknown_finding_refuses_everything(self):
        uc, store = _use_case(facts=make_facts(exists=False, draft_pr_url=None, finding_resolved=False))
        with pytest.raises(EntryGateNotSatisfiedError) as exc:
            uc.execute(_command())
        assert REASON_NOT_APPLIED in exc.value.unmet
        assert REASON_NOT_RESOLVED in exc.value.unmet
        assert store.saved == []


class TestProvenanceAndRawCode:
    def test_entry_links_provenance_and_stores_raw_code(self):
        uc, _ = _use_case(facts=make_facts(provenance_event_ref="agent:triage@t9", draft_pr_url=_PR_URL))
        entry = uc.execute(_command(code="<script>alert(1)</script>"))
        # Provenance is linked, not duplicated.
        assert entry.provenance_event_ref == "agent:triage@t9"
        assert entry.finding_task_id == "task-1"
        # Code is stored RAW — angle brackets survive verbatim (never rendered HTML).
        assert entry.code == "<script>alert(1)</script>"
        assert "&lt;" not in entry.code
