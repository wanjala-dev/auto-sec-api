"""The mode reaches the persisted row (ADR 0035 D5).

A value object nothing writes down is not an audit trail. These pin the last
hop: that `ToolCallObservation.as_payload()` — the governance block appended to
every `tool_observation` row — carries the mode when it is known, and stays
silent when it is not.

The distinction in the second half is the whole design. A call we observed but
could not classify, and a call written before the field existed, must not look
the same in the database.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_spec import ToolCallObservation, ToolOutcome

pytestmark = [pytest.mark.unit]


def _observation(**over):
    base = {
        "tool_name": "open_draft_pr",
        "tool_call_id": "call-1",
        "outcome": ToolOutcome.SUCCESS,
        "latency_ms": 12,
    }
    base.update(over)
    return ToolCallObservation(**base)


class TestTheModeReachesTheRow:
    def test_a_recorded_mode_is_on_the_payload(self):
        payload = _observation(autonomy_mode="autonomous").as_payload()

        assert payload["autonomy_mode"] == "autonomous"

    def test_it_rides_alongside_the_existing_governance_fields(self):
        """It joins the block already written per call rather than adding a
        second row — one call, one governance record."""
        payload = _observation(autonomy_mode="assist", declared=True).as_payload()

        assert payload["outcome"] == ToolOutcome.SUCCESS
        assert payload["declared"] is True
        assert payload["autonomy_mode"] == "assist"

    def test_a_refused_call_still_records_its_mode(self):
        """A DENIED call is the one an incident review most wants to read, so it
        is the last place the mode should go missing."""
        payload = _observation(outcome=ToolOutcome.FAILURE, failure="denied", autonomy_mode="evaluation").as_payload()

        assert payload["failure"] == "denied"
        assert payload["autonomy_mode"] == "evaluation"


class TestAbsenceIsNotAValue:
    def test_an_unstamped_call_writes_no_mode_key_at_all(self):
        """Not `"unknown"`. Emitting a value here would make a call we DID
        observe but could not classify indistinguishable from a row written
        before the field existed — and telling those apart is the point."""
        payload = _observation().as_payload()

        assert "autonomy_mode" not in payload

    def test_the_default_is_empty_rather_than_a_guess(self):
        """It never defaults to ASSIST. A stamp that fails must leave the row
        saying nothing, because a wrong governance answer is worse than a
        missing one."""
        assert _observation().autonomy_mode == ""
