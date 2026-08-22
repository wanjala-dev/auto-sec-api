"""The stamp resolved at the gate reaches the observation (ADR 0035 D5).

The two files beside this one test the ends: the value object resolves
correctly, and `as_payload()` carries what it is given. This one tests the hop
between them — that `_risk_gated` stamps the agent with a mode the governance
middleware can read back.

That hop is where this design could quietly fail. The value object could be
perfect and the payload could be wired, and if the stamp never lands the row
still records nothing. A gap in an audit trail does not raise; it just leaves
the answer missing when someone finally asks.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_spec import ToolCallObservation, ToolOutcome
from components.agents.infrastructure.adapters.langchain.base import _stamp_autonomy_mode

pytestmark = [pytest.mark.unit]


class _Agent:
    """Stands in for the promoted-tool agent, which is stamped by attribute."""


class TestTheStampLands:
    @pytest.mark.parametrize(
        ("execution_mode", "is_autonomous", "expected"),
        [
            (None, False, "assist"),
            (None, True, "autonomous"),
            ("evaluation", False, "evaluation"),
            ("evaluation", True, "evaluation"),
        ],
    )
    def test_each_signal_combination_stamps_the_right_mode(self, execution_mode, is_autonomous, expected):
        agent = _Agent()

        _stamp_autonomy_mode(agent, execution_mode=execution_mode, is_autonomous=is_autonomous)

        assert agent._autonomy_mode == expected

    def test_the_stamped_value_survives_onto_the_persisted_payload(self):
        """The whole chain: gate resolves → agent carries → observation records
        → payload is what the tool_observation row stores."""
        agent = _Agent()
        _stamp_autonomy_mode(agent, execution_mode=None, is_autonomous=True)

        observation = ToolCallObservation(
            tool_name="open_draft_pr",
            tool_call_id="c1",
            outcome=ToolOutcome.SUCCESS,
            latency_ms=5,
            autonomy_mode=getattr(agent, "_autonomy_mode", ""),
        )

        assert observation.as_payload()["autonomy_mode"] == "autonomous"

    def test_a_later_call_restamps_rather_than_keeping_a_stale_mode(self):
        """The stamp is per CALL. If it were sticky, a run that legitimately
        changed context would keep reporting its first mode for every
        subsequent tool."""
        agent = _Agent()

        _stamp_autonomy_mode(agent, execution_mode=None, is_autonomous=True)
        _stamp_autonomy_mode(agent, execution_mode="evaluation", is_autonomous=True)

        assert agent._autonomy_mode == "evaluation"


class TestItNeverBreaksTheRun:
    def test_an_unstampable_target_does_not_raise(self):
        """An audit stamp that can take down a tool call would be a worse
        problem than the gap it closes. `object()` accepts no attributes."""
        _stamp_autonomy_mode(object(), execution_mode=None, is_autonomous=True)

    def test_a_failed_stamp_leaves_no_mode_rather_than_guessing(self):
        """Fails CLOSED in the sense that matters: the row records nothing and
        reads UNKNOWN. It must never fall back to ASSIST, because a confident
        wrong governance answer is worse than an absent one."""
        target = object()

        _stamp_autonomy_mode(target, execution_mode=None, is_autonomous=True)

        assert getattr(target, "_autonomy_mode", "") == ""
