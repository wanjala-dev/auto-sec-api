"""Pure-unit coverage for the run-telemetry stamp helpers (task #58).

The ORM-touching path (stamping real finding rows post-dispatch) lives in
``tests/integration/test_run_telemetry_stamp.py``; here we pin the pure
attribution logic and the no-telemetry short-circuit.
"""

from __future__ import annotations

from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
    _telemetry_entry_for,
    stamp_run_telemetry_on_findings,
)


class TestTelemetryEntryFor:
    def test_exact_key_match_wins_and_is_task_scoped(self):
        per_task = {"f-1": {"verdict": "satisfied"}, "f-2": {"verdict": "failed"}}
        entry = _telemetry_entry_for(per_task, "f-2")
        assert entry == {"verdict": "failed", "scope": "task"}

    def test_single_entry_map_applies_run_scoped(self):
        # One plan task graded the whole batch — its verdict applies to every
        # finding the batch handled, marked as run-scoped.
        per_task = {"plan-task-uuid": {"verdict": "satisfied", "iterations": 1}}
        entry = _telemetry_entry_for(per_task, "f-9")
        assert entry == {"verdict": "satisfied", "iterations": 1, "scope": "run"}

    def test_ambiguous_multi_entry_map_is_not_fabricated(self):
        per_task = {"t1": {"verdict": "satisfied"}, "t2": {"verdict": "failed"}}
        assert _telemetry_entry_for(per_task, "f-unmatched") is None

    def test_empty_or_malformed_map_is_none(self):
        assert _telemetry_entry_for({}, "f-1") is None
        assert _telemetry_entry_for(None, "f-1") is None
        assert _telemetry_entry_for({"only": "not-a-dict"}, "f-1") is None


class TestStampShortCircuits:
    """Paths that must return 0 BEFORE touching the ORM (safe without DB)."""

    def test_no_final_output_stamps_nothing(self):
        assert (
            stamp_run_telemetry_on_findings(
                workspace_id="ws-1",
                specialist="triage_agent",
                since=None,
                run_result={"success": False, "error": "agent_not_entitled"},
            )
            == 0
        )

    def test_empty_run_metadata_stamps_nothing(self):
        assert (
            stamp_run_telemetry_on_findings(
                workspace_id="ws-1",
                specialist="triage_agent",
                since=None,
                run_result={"success": True, "final_output": {"answer": "ok", "run_metadata": {}}},
            )
            == 0
        )

    def test_non_dict_result_stamps_nothing(self):
        assert (
            stamp_run_telemetry_on_findings(workspace_id="ws-1", specialist="triage_agent", since=None, run_result=None)
            == 0
        )
