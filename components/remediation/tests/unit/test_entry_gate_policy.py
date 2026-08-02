"""The pure gate rule: all three conditions must hold, in one place."""

from __future__ import annotations

import itertools

import pytest

from components.remediation.domain.errors import EntryGateNotSatisfiedError
from components.remediation.domain.services.entry_gate_policy import EntryGatePolicy
from components.remediation.domain.value_objects.gate_conditions import (
    REASON_NOT_APPLIED,
    REASON_NOT_APPROVED,
    REASON_NOT_RESOLVED,
    GateConditions,
)

pytestmark = pytest.mark.unit


class TestGateConditions:
    def test_all_three_true_is_satisfied(self):
        c = GateConditions(sign_off_approved=True, draft_pr_applied=True, finding_resolved=True)
        assert c.satisfied is True
        assert c.unmet_reasons() == ()
        assert EntryGatePolicy.is_admissible(c) is True

    @pytest.mark.parametrize(
        "approved,applied,resolved",
        [combo for combo in itertools.product([True, False], repeat=3) if not all(combo)],
    )
    def test_any_missing_condition_is_not_satisfied(self, approved, applied, resolved):
        c = GateConditions(sign_off_approved=approved, draft_pr_applied=applied, finding_resolved=resolved)
        assert c.satisfied is False
        assert EntryGatePolicy.is_admissible(c) is False

    def test_unmet_reasons_name_each_missing_condition(self):
        c = GateConditions(sign_off_approved=False, draft_pr_applied=False, finding_resolved=False)
        assert c.unmet_reasons() == (REASON_NOT_APPROVED, REASON_NOT_APPLIED, REASON_NOT_RESOLVED)

    def test_enforce_raises_only_when_unsatisfied(self):
        ok = GateConditions(sign_off_approved=True, draft_pr_applied=True, finding_resolved=True)
        EntryGatePolicy.enforce(ok)  # no raise

        bad = GateConditions(sign_off_approved=True, draft_pr_applied=True, finding_resolved=False)
        with pytest.raises(EntryGateNotSatisfiedError) as exc:
            EntryGatePolicy.enforce(bad)
        assert REASON_NOT_RESOLVED in exc.value.unmet
