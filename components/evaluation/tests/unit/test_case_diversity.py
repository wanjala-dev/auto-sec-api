"""A denominator built from duplicates is worse than no denominator.

The scenario in `test_the_live_demo_workspace_shape` is not invented — it is
the live demo workspace measured on 2026-08-21: 1,645 findings suppressed in a
single minute under one reason string. A miner that counted rows would have
called that 1,645 cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from components.evaluation.domain.services.case_diversity import (
    DecisionRecord,
    availability,
    collapse_to_distinct,
    normalise_reason,
)
from components.evaluation.domain.value_objects.claim_tier import (
    MIN_OBSERVATIONS,
    ClaimTier,
    tier_for,
)

pytestmark = [pytest.mark.unit]

BULK_AT = datetime(2026, 8, 9, 22, 10, 0)


def _record(ref: str, reason: str, at: datetime | None = BULK_AT, label: str = "bad"):
    return DecisionRecord(
        source_ref=ref,
        source_kind="finding",
        reason=reason,
        decided_at=at,
        label=label,
    )


class TestBulkActionsCollapse:
    def test_the_live_demo_workspace_shape(self):
        """1,645 rows, one reason, one minute -> ONE distinct decision."""
        reason = "demo scan of public image — no remediation target (suppressed)"
        records = [_record(f"finding-{i}", reason) for i in range(1645)]

        distinct = collapse_to_distinct(records)

        assert len(distinct) == 1
        assert distinct[0].duplicate_count == 1645

    def test_that_cluster_does_not_clear_the_measurement_floor(self):
        """The whole point: 1,645 rows must NOT buy an aggregate-grade claim."""
        reason = "demo scan of public image — no remediation target (suppressed)"
        records = [_record(f"finding-{i}", reason) for i in range(1645)]

        report = availability(records, required=MIN_OBSERVATIONS)

        assert report.raw_rows == 1645
        assert report.distinct_decisions == 1
        assert tier_for(report.distinct_decisions) is ClaimTier.NOT_MEASURED
        assert report.is_sufficient is False
        assert report.shortfall == MIN_OBSERVATIONS - 1

    def test_the_misleading_raw_count_is_still_reported(self):
        """Reported, because hiding it is how "1,646 available!" gets said out
        loud somewhere else. The surface shows both numbers together."""
        records = [_record(f"f-{i}", "same reason") for i in range(50)]

        report = availability(records, required=MIN_OBSERVATIONS)

        assert report.raw_rows == 50
        assert report.largest_cluster == 50
        assert report.distinct_decisions == 1


class TestGenuineJudgementsSurvive:
    def test_different_rationales_are_different_decisions(self):
        records = [
            _record("f-1", "false positive: test fixture, not shipped"),
            _record("f-2", "accepted risk: internal-only service"),
            _record("f-3", "duplicate of INFRA-221"),
        ]

        assert len(collapse_to_distinct(records)) == 3

    def test_the_same_rationale_minutes_apart_stays_distinct(self):
        """A reviewer working through a queue is making separate judgements,
        even when they write the same words each time."""
        records = [
            _record("f-1", "false positive", at=BULK_AT),
            _record("f-2", "false positive", at=BULK_AT + timedelta(minutes=3)),
            _record("f-3", "false positive", at=BULK_AT + timedelta(minutes=9)),
        ]

        assert len(collapse_to_distinct(records)) == 3

    def test_opposite_labels_never_merge(self):
        """A confirmed finding and a suppressed one are different evidence even
        if someone typed the same note."""
        records = [
            _record("f-1", "reviewed", label="good"),
            _record("f-2", "reviewed", label="bad"),
        ]

        assert len(collapse_to_distinct(records)) == 2

    def test_trivial_edits_do_not_fake_variety(self):
        """Whitespace and casing are not judgement."""
        records = [
            _record("f-1", "False Positive"),
            _record("f-2", "false   positive"),
            _record("f-3", "  false positive  "),
        ]

        assert len(collapse_to_distinct(records)) == 1


class TestRepresentativeAndEdges:
    def test_the_representative_is_the_earliest_member(self):
        records = [
            _record("late", "same", at=BULK_AT + timedelta(seconds=30)),
            _record("early", "same", at=BULK_AT),
        ]

        distinct = collapse_to_distinct(records)

        assert distinct[0].representative.source_ref == "early"

    def test_records_without_timestamps_group_on_rationale_alone(self):
        """Splitting further would invent variety we cannot evidence."""
        records = [_record("f-1", "no timestamp", at=None), _record("f-2", "no timestamp", at=None)]

        assert len(collapse_to_distinct(records)) == 1

    def test_an_empty_history_is_reported_as_empty(self):
        report = availability([], required=MIN_OBSERVATIONS)

        assert report.distinct_decisions == 0
        assert report.largest_cluster == 0
        assert report.is_sufficient is False

    def test_enough_distinct_decisions_is_sufficient(self):
        records = [_record(f"f-{i}", f"distinct reason {i}") for i in range(MIN_OBSERVATIONS)]

        report = availability(records, required=MIN_OBSERVATIONS)

        assert report.distinct_decisions == MIN_OBSERVATIONS
        assert report.is_sufficient is True
        assert report.shortfall == 0

    def test_a_scenario_is_derived_from_the_rationale(self):
        distinct = collapse_to_distinct([_record("f-1", "accepted risk: internal-only service")])

        assert distinct[0].scenario == "accepted risk: internal-only service"

    def test_a_missing_rationale_says_so_rather_than_rendering_blank(self):
        distinct = collapse_to_distinct([_record("f-1", "")])

        assert "no rationale recorded" in distinct[0].scenario

    def test_normalisation_is_idempotent(self):
        once = normalise_reason("  False   Positive ")
        assert normalise_reason(once) == once
