"""Unit tests for ``TaskSerializer.get_sign_off``.

The unified AI-team board renders the pending-sign-off review affordance
(risk badge, receipts, approve/reject) on the real TaskCard. That is only
possible because the serializer surfaces a lean ``sign_off`` object pulled
from ``metadata.context`` for sign-off tasks (source_type ==
SIGN_OFF_SOURCE_TYPE) and ``None`` for every other task.

These are pure-mapper tests: ``get_sign_off`` only reads attributes off the
object, so a light stub stands in for a Task ORM instance — no DB needed.
"""

from types import SimpleNamespace

import pytest

from components.project.mappers.rest.project_serializers import TaskSerializer
from components.sign_off.application.services.materialize_signoff_tasks import (
    SIGN_OFF_SOURCE_TYPE,
)


def _serializer():
    # get_sign_off never touches serializer state, so a bare instance is fine.
    return TaskSerializer.__new__(TaskSerializer)


def _sign_off_task(**overrides):
    context = {
        "artifact_type": "financial_report",
        "artifact_id": "11111111-1111-1111-1111-111111111111",
        "risk_band": "amber",
        "receipts_summary": {
            "unverified_figures": 2,
            "ungrounded_claims": 0,
            "voice_flags": 1,
            "is_clean": False,
        },
    }
    context.update(overrides.pop("context", {}))
    task = SimpleNamespace(
        source_type=SIGN_OFF_SOURCE_TYPE,
        metadata={"context": context},
    )
    for key, value in overrides.items():
        setattr(task, key, value)
    return task


class TestTaskSerializerSignOff:
    def test_sign_off_task_exposes_artifact_ref_band_and_receipts(self):
        result = _serializer().get_sign_off(_sign_off_task())
        assert result == {
            "artifact_type": "financial_report",
            "artifact_id": "11111111-1111-1111-1111-111111111111",
            "risk_band": "amber",
            "receipts_summary": {
                "unverified_figures": 2,
                "ungrounded_claims": 0,
                "voice_flags": 1,
                "is_clean": False,
            },
        }

    def test_non_sign_off_task_returns_none(self):
        task = SimpleNamespace(
            source_type="ai.donor_payment_succeeded",
            metadata={"context": {"artifact_type": "x", "artifact_id": "y"}},
        )
        assert _serializer().get_sign_off(task) is None

    def test_human_task_with_no_source_type_returns_none(self):
        task = SimpleNamespace(source_type="", metadata=None)
        assert _serializer().get_sign_off(task) is None

    def test_sign_off_task_missing_artifact_ref_returns_none(self):
        # A malformed context (no artifact_type/id) must not produce a
        # half-populated ref the frontend would then try to approve.
        task = _sign_off_task(context={"artifact_type": None, "artifact_id": None})
        assert _serializer().get_sign_off(task) is None

    def test_artifact_id_is_stringified(self):
        # Whatever the context stored (uuid/int), the wire contract is a str.
        task = _sign_off_task(context={"artifact_id": 42})
        result = _serializer().get_sign_off(task)
        assert result["artifact_id"] == "42"

    def test_missing_receipts_summary_defaults_to_empty_dict(self):
        task = _sign_off_task(context={"receipts_summary": None, "risk_band": None})
        result = _serializer().get_sign_off(task)
        assert result["receipts_summary"] == {}
        assert result["risk_band"] == ""


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
