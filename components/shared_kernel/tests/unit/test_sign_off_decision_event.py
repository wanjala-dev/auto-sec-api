"""Unit tests for the ``SignOffDecisionRecorded`` shared-kernel event (SEE-190).

The event ferries a reviewer decision from ``sign_off`` to the ``agents``
feedback→eval handler over the Celery wire, so it MUST round-trip cleanly
through ``_serialise_event`` / ``_deserialise_event`` — in particular
``reason_codes`` must survive as a ``list`` (a tuple would deserialise wrong and
break the handler's ``list(event.reason_codes)`` read).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.shared_kernel.domain.events import SignOffDecisionRecorded
from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
    _deserialise_event,
    _serialise_event,
)

_FQN = (
    "components.shared_kernel.domain.events.SignOffDecisionRecorded"
)


@pytest.mark.unit
class TestSignOffDecisionRecorded:
    def test_build_with_fields(self):
        event = SignOffDecisionRecorded(
            artifact_type="newsletter",
            artifact_id="n1",
            decision="changes_requested",
            risk_band="amber",
            reason_codes=["unsupported_figure", "off_voice"],
            note="fix the number",
            actor_id="u1",
            workspace_id="w1",
        )
        assert event.artifact_type == "newsletter"
        assert event.reason_codes == ["unsupported_figure", "off_voice"]
        assert event.event_id is not None
        assert event.occurred_at is not None

    def test_defaults(self):
        event = SignOffDecisionRecorded(
            artifact_type="newsletter",
            artifact_id="n1",
            decision="approved",
            risk_band="red",
        )
        assert event.reason_codes == []
        assert event.note == ""
        assert event.actor_id is None
        assert event.workspace_id is None

    def test_round_trip_preserves_fields_and_list_type(self):
        event = SignOffDecisionRecorded(
            artifact_type="writing_draft",
            artifact_id=str(uuid4()),
            decision="rejected",
            risk_band="red",
            reason_codes=["fabricated_quote", "off_topic"],
            note="invented a quote",
            actor_id=str(uuid4()),
            workspace_id=str(uuid4()),
        )
        data = _serialise_event(event)
        # reason_codes is JSON-serialised as a list, never a tuple.
        assert isinstance(data["reason_codes"], list)

        rebuilt = _deserialise_event(_FQN, data)
        assert isinstance(rebuilt, SignOffDecisionRecorded)
        assert rebuilt.artifact_type == event.artifact_type
        assert rebuilt.artifact_id == event.artifact_id
        assert rebuilt.decision == "rejected"
        assert rebuilt.risk_band == "red"
        assert rebuilt.note == "invented a quote"
        assert rebuilt.actor_id == event.actor_id
        assert rebuilt.workspace_id == event.workspace_id
        # The load-bearing assertion: reason_codes stays a list post round-trip.
        assert isinstance(rebuilt.reason_codes, list)
        assert rebuilt.reason_codes == ["fabricated_quote", "off_topic"]

    def test_round_trip_empty_reason_codes(self):
        event = SignOffDecisionRecorded(
            artifact_type="newsletter",
            artifact_id="n1",
            decision="approved",
            risk_band="red",
        )
        data = _serialise_event(event)
        rebuilt = _deserialise_event(_FQN, data)
        assert isinstance(rebuilt.reason_codes, list)
        assert rebuilt.reason_codes == []
