"""What autonomy a run executed under (ADR 0035 D5).

These are governance assertions, not feature ones. The property under test is
that the recorded answer describes what was ACTUALLY permitted at the time, and
keeps describing it after the settings change.

The trap being closed is the one `tool_risk.py` already documents for risk
tiers: re-derive a historical value from a live config and "every `delete_task`
already in the database retroactively reports as a `read`". For autonomy the
consequence is sharper — switch a workspace to AUTONOMOUS on Friday and every
past ASSIST run looks autonomous, which is exactly the question an incident
review asks first.
"""

from __future__ import annotations

import pytest

from components.agents.domain.value_objects.autonomy_mode import (
    UNRECORDED,
    AutonomyMode,
    parse,
    resolve,
)

pytestmark = [pytest.mark.unit]


class TestResolution:
    def test_a_normal_run_is_assist(self):
        """Today's default, and the one that must not change on deploy."""
        assert resolve(execution_mode=None, is_autonomous=False) is AutonomyMode.ASSIST

    def test_a_service_principal_run_is_autonomous(self):
        assert resolve(execution_mode=None, is_autonomous=True) is AutonomyMode.AUTONOMOUS

    def test_an_eval_run_is_evaluation(self):
        assert resolve(execution_mode="evaluation", is_autonomous=False) is AutonomyMode.EVALUATION

    def test_evaluation_beats_autonomy(self):
        """An eval run driven by a service principal is still an eval run, and
        it is the STRICTER of the two — only declared reads execute. Recording
        it as AUTONOMOUS would overstate what it was permitted to do."""
        assert resolve(execution_mode="evaluation", is_autonomous=True) is AutonomyMode.EVALUATION

    def test_the_execution_mode_string_is_read_forgivingly(self):
        assert resolve(execution_mode="  EVALUATION ", is_autonomous=False) is AutonomyMode.EVALUATION

    def test_an_unrecognised_execution_mode_does_not_become_evaluation(self):
        """Only the exact mode grants evaluation's stricter reading. A typo must
        fall through to the ordinary ladder rather than silently claiming the
        run was sandboxed."""
        assert resolve(execution_mode="evaluatoin", is_autonomous=True) is AutonomyMode.AUTONOMOUS

    def test_manual_is_not_yet_reachable(self):
        """MANUAL exists in the vocabulary but nothing can select it until the
        setting lands (D2/D6). A mode nothing produces is honest; a mode that
        silently means something else is not — so this pins that resolve()
        never invents one."""
        produced = {
            resolve(execution_mode=m, is_autonomous=a)
            for m in (None, "", "evaluation", "anything")
            for a in (True, False)
        }
        assert AutonomyMode.MANUAL not in produced


class TestUnknownIsARealValue:
    def test_an_absent_stored_value_is_unknown(self):
        """Rows written before the field existed. Never back-filled: doing so
        would manufacture a governance claim about runs nobody observed."""
        assert parse(None) is AutonomyMode.UNKNOWN
        assert parse("") is AutonomyMode.UNKNOWN

    def test_an_unreadable_value_is_unknown_rather_than_an_exception(self):
        """A governance READ must never be the thing that takes a page down,
        and a value we cannot interpret IS a mode we do not know."""
        assert parse("something-else-entirely") is AutonomyMode.UNKNOWN

    def test_unknown_does_not_masquerade_as_a_real_mode(self):
        assert UNRECORDED is AutonomyMode.UNKNOWN
        assert AutonomyMode.UNKNOWN.is_recorded is False
        assert all(m.is_recorded for m in AutonomyMode if m is not AutonomyMode.UNKNOWN)

    def test_every_recorded_mode_round_trips(self):
        for mode in AutonomyMode:
            assert parse(mode.value) is mode


class TestLabels:
    def test_every_mode_has_one(self):
        assert {m.label for m in AutonomyMode} == {
            "MANUAL",
            "ASSIST",
            "AUTONOMOUS",
            "EVALUATION",
            "UNKNOWN",
        }
