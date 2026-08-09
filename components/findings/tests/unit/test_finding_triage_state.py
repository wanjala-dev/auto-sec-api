"""Every finding must have an honest, derivable answer to "where is my fix?".

These lock the read half of the contract: a finding is NEVER an unexplained blank,
each state comes from data that actually exists on the board card, and the finished
states always win over a stale in-flight stamp.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from components.findings.application.queries.finding_triage_state_query import derive_triage_state
from components.shared_kernel.domain.triage import TriageState

pytestmark = pytest.mark.unit

_NEXT = datetime(2026, 8, 8, 15, 35, tzinfo=UTC)


def _card(metadata=None, source_type="ai.code_security", task_id="42"):
    base = {"agent_type": "code_security_agent"}
    base.update(metadata or {})
    return {"source_type": source_type, "task_id": task_id, "metadata": base}


def test_no_board_card_is_not_routed_with_a_reason():
    """A finding below the board threshold still explains itself."""
    state = derive_triage_state(card=None)
    assert state.state == TriageState.NOT_ROUTED.value
    assert state.reason  # never a blank


def test_operator_reading_finding_is_not_routed():
    """Cloud posture / planted instructions have no automated fix path — say so
    plainly rather than showing a permanently empty fix panel."""
    state = derive_triage_state(card=_card(source_type="ai.cloud_posture"))
    assert state.state == TriageState.NOT_ROUTED.value
    assert "no automated fix path" in state.reason


def test_orchestrator_targeted_card_is_not_routed():
    state = derive_triage_state(card=_card(metadata={"agent_type": "ai_teammate"}))
    assert state.state == TriageState.NOT_ROUTED.value


def test_fresh_finding_is_queued_and_names_the_next_pass():
    """The core fix for Henry's complaint: a just-detected finding says QUEUED and
    WHEN the next pass runs, instead of showing nothing."""
    state = derive_triage_state(card=_card(), next_triage_at=_NEXT)
    assert state.state == TriageState.QUEUED.value
    assert state.next_triage_at == _NEXT
    assert state.specialist == "code_security_agent"
    assert state.can_draft_fix is True
    assert state.reason


def test_in_flight_dispatch_shows_drafting():
    state = derive_triage_state(card=_card(), dispatch_stamp_is_fresh=True)
    assert state.state == TriageState.DRAFTING.value
    assert "drafting a fix right now" in state.reason


def test_triaged_with_a_suggestion_is_fix_ready():
    state = derive_triage_state(
        card=_card(
            metadata={
                "triage": {"status": "triaged", "suggested": True, "triaged_at": "2026-08-08T15:20:00+00:00"},
                "payload": {"suggested_fix": "Use parameterised queries", "confidence": "high"},
            }
        )
    )
    assert state.state == TriageState.FIX_READY.value
    assert state.suggested_fix == "Use parameterised queries"
    assert state.confidence == "high"
    assert state.can_draft_fix is True


def test_fix_ready_with_an_open_pr_no_longer_offers_to_draft_one():
    state = derive_triage_state(
        card=_card(
            metadata={
                "triage": {"status": "triaged", "suggested": True},
                "payload": {
                    "suggested_fix": "x",
                    "draft_pr": {"url": "https://github.com/o/r/pull/1", "repo": "o/r"},
                },
            }
        )
    )
    assert state.state == TriageState.FIX_READY.value
    assert state.draft_pr["url"].endswith("/pull/1")
    assert state.can_draft_fix is False


def test_ungrounded_fix_is_needs_human_and_carries_the_recorded_reason():
    """The grounded verifier's decision must reach the operator verbatim — a
    confident-but-ungrounded fix never becomes a PR, and they must see why."""
    state = derive_triage_state(
        card=_card(
            metadata={
                "triage": {"status": "triaged", "suggested": True, "needs_human": True},
                "payload": {
                    "needs_human": True,
                    "needs_human_reason": "The source file contains text shaped like instructions to an AI assistant",
                    "suggested_fix": "…",
                },
            }
        )
    )
    assert state.state == TriageState.NEEDS_HUMAN.value
    assert "instructions to an AI assistant" in state.reason


def test_triaged_without_a_suggestion_is_no_fix():
    state = derive_triage_state(card=_card(metadata={"triage": {"status": "triaged", "suggested": False}}))
    assert state.state == TriageState.NO_FIX.value
    assert "could not derive a confident fix" in state.reason


def test_a_blocked_pull_request_is_visible_not_silent():
    """A guardrail refusal (throttle, scope, low confidence) must surface — a click
    that opened nothing with no explanation is the failure mode being removed."""
    state = derive_triage_state(
        card=_card(
            metadata={
                "triage": {"status": "triaged", "suggested": True},
                "payload": {"suggested_fix": "x"},
                "draft_pr_blocked": {"reason": "sast_pr_throttled", "message": "3 draft PRs already open"},
            }
        )
    )
    assert state.state == TriageState.FIX_READY.value
    assert state.blocked_reason == "sast_pr_throttled"
    assert "already open" in state.reason


def test_a_finished_fix_beats_a_stale_in_flight_stamp():
    """Order matters: a leftover ``triage_dispatch`` must never mask a landed fix."""
    state = derive_triage_state(
        card=_card(
            metadata={
                "triage": {"status": "triaged", "suggested": True},
                "payload": {"suggested_fix": "x"},
                "triage_dispatch": {"state": "drafting", "at": "2026-08-08T15:00:00+00:00"},
            }
        ),
        dispatch_stamp_is_fresh=True,
    )
    assert state.state == TriageState.FIX_READY.value


def test_stale_stamp_falls_back_to_queued_not_drafting_forever():
    """A dispatch whose worker died must not spin on DRAFTING — the finding returns
    to QUEUED with the next cadence pass named."""
    state = derive_triage_state(card=_card(), next_triage_at=_NEXT, dispatch_stamp_is_fresh=False)
    assert state.state == TriageState.QUEUED.value
    assert state.next_triage_at == _NEXT


def test_every_state_carries_a_reason():
    """The invariant behind the whole change: no state is ever an unexplained blank."""
    cases = [
        derive_triage_state(card=None),
        derive_triage_state(card=_card(source_type="ai.cloud_posture")),
        derive_triage_state(card=_card(), next_triage_at=_NEXT),
        derive_triage_state(card=_card(), dispatch_stamp_is_fresh=True),
        derive_triage_state(card=_card(metadata={"triage": {"status": "triaged", "suggested": False}})),
        derive_triage_state(
            card=_card(metadata={"triage": {"status": "triaged", "needs_human": True, "suggested": True}})
        ),
    ]
    for state in cases:
        assert state.reason, f"{state.state} has no operator-facing reason"


class TestStampFreshness:
    """The DRAFTING stamp is believed only inside its contract window."""

    def test_fresh_stamp_is_believed(self):
        from components.findings.infrastructure.repositories.board_triage_state_repository import (
            _stamp_is_fresh,
        )

        now = datetime.now(UTC)
        assert _stamp_is_fresh({"at": now.isoformat()}, now - timedelta(seconds=600)) is True

    def test_expired_stamp_is_not_believed(self):
        from components.findings.infrastructure.repositories.board_triage_state_repository import (
            _stamp_is_fresh,
        )

        now = datetime.now(UTC)
        old = (now - timedelta(seconds=1200)).isoformat()
        assert _stamp_is_fresh({"at": old}, now - timedelta(seconds=600)) is False

    def test_naive_stamp_against_aware_window_does_not_explode(self):
        """Regression (found live): the stamp is a STRING whose awareness follows the
        writing deployment's USE_TZ, while the comparison window follows this
        process's. Coercing only one side raised "can't compare offset-naive and
        offset-aware datetimes" on the DRAFTING path, and the fail-safe swallowed it
        so every finding silently lost its triage block."""
        from components.findings.infrastructure.repositories.board_triage_state_repository import (
            _stamp_is_fresh,
        )

        aware_window = datetime.now(UTC) - timedelta(seconds=600)
        naive_now = datetime.now(UTC).replace(tzinfo=None)
        assert _stamp_is_fresh({"at": naive_now.isoformat()}, aware_window) is True

    def test_aware_stamp_against_naive_window_does_not_explode(self):
        """The mirror case: USE_TZ=False in this process (the local k8s overlay),
        a tz-aware stamp on the card."""
        from components.findings.infrastructure.repositories.board_triage_state_repository import (
            _stamp_is_fresh,
        )

        naive_window = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=600)
        aware_now = datetime.now(UTC)
        assert _stamp_is_fresh({"at": aware_now.isoformat()}, naive_window) is True

    def test_naive_expired_stamp_against_aware_window_is_stale(self):
        from components.findings.infrastructure.repositories.board_triage_state_repository import (
            _stamp_is_fresh,
        )

        aware_window = datetime.now(UTC) - timedelta(seconds=600)
        naive_old = (datetime.now(UTC) - timedelta(seconds=1200)).replace(tzinfo=None)
        assert _stamp_is_fresh({"at": naive_old.isoformat()}, aware_window) is False

    @pytest.mark.parametrize("stamp", [None, {}, {"at": ""}, {"at": "not-a-date"}, "nonsense"])
    def test_malformed_stamp_is_not_believed(self, stamp):
        from components.findings.infrastructure.repositories.board_triage_state_repository import (
            _stamp_is_fresh,
        )

        assert _stamp_is_fresh(stamp, datetime.now(UTC)) is False


def test_next_cadence_run_at_is_derived_from_the_real_beat_schedule():
    """The operator-facing "next pass ~HH:MM" must come from what Beat actually
    does, not a hard-coded guess that can silently drift."""
    from components.findings.infrastructure.repositories.board_triage_state_repository import (
        next_cadence_run_at,
    )

    now = datetime.now(UTC)
    nxt = next_cadence_run_at(now)
    assert nxt is not None
    assert nxt > now
    # The router cadence is every 5 minutes, so the next pass is always within one.
    assert (nxt - now) <= timedelta(minutes=5, seconds=1)
