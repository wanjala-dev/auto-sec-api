"""Pure unit tests for the AI-governance query service (Phase 2 AI-SPM slice).

No DB, no LLM — these pin the deterministic aggregation core: run/tool-call
counting by dispatch source and risk tier, the capability-grant shaping with
honest "not audited" flags, the HITL ledger's window math on MIXED
naive/aware timestamps (fix #34 — metadata timestamps are naive isoformat
strings while DB datetimes are aware), the secret-free credential inventory,
and the kill-switch status composition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.services.ai_governance_service import (
    APPROVAL_DENIALS_NOTE,
    DISPATCH_SOURCE_CHAT,
    DISPATCH_SOURCE_DETECTOR,
    _parse_iso,
    compute_ai_activity,
    compute_capability_grants,
    compute_credential_inventory,
    compute_hitl_ledger,
    compute_kill_switch_status,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class TestParseIso:
    def test_aware_datetime_passthrough(self):
        aware = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
        assert _parse_iso(aware) == aware

    def test_naive_datetime_assumed_utc(self):
        naive = datetime(2026, 7, 20, 10, 0)
        parsed = _parse_iso(naive)
        assert parsed.tzinfo is UTC

    def test_naive_iso_string_assumed_utc(self):
        # The live-data shape: draft_pr.opened_at written with
        # datetime.now().isoformat() has no offset.
        parsed = _parse_iso("2026-07-20T10:00:00")
        assert parsed == datetime(2026, 7, 20, 10, 0, tzinfo=UTC)

    def test_garbage_and_empty_are_none(self):
        assert _parse_iso("not-a-date") is None
        assert _parse_iso("") is None
        assert _parse_iso(None) is None
        assert _parse_iso(123) is None


def _run(i, *, status="completed", source=DISPATCH_SOURCE_CHAT):
    return {"id": f"run-{i}", "status": status, "source": source}


def _tool(agent="TriageAgent", tool="list_open_findings", risk=ToolRisk.READ):
    return {"agent_type": agent, "tool_name": tool, "risk": risk}


class TestComputeAiActivity:
    def test_runs_bucketed_by_status_and_source(self):
        runs = [
            _run(1, status="completed", source=DISPATCH_SOURCE_CHAT),
            _run(2, status="failed", source=DISPATCH_SOURCE_CHAT),
            _run(3, status="completed", source=DISPATCH_SOURCE_DETECTOR),
        ]
        out = compute_ai_activity(runs, [], now=NOW, window_days=7)

        assert out["runs"]["total"] == 3
        assert out["runs"]["by_status"] == {"completed": 2, "failed": 1}
        assert out["runs"]["by_source"] == {"chat": 2, "detector": 1}
        assert out["runs"]["sample_run_ids"] == ["run-1", "run-2", "run-3"]
        assert out["window_days"] == 7

    def test_unknown_source_is_bucketed_honestly_not_guessed(self):
        out = compute_ai_activity([{"id": "r", "status": "completed", "source": "??"}], [], now=NOW, window_days=7)
        assert out["runs"]["by_source"] == {"unknown": 1}

    def test_tool_calls_counted_by_tool_agent_and_risk(self):
        tools = [
            _tool(tool="list_open_findings", risk=ToolRisk.READ),
            _tool(tool="triage_finding", risk=ToolRisk.REVERSIBLE_WRITE),
            _tool(tool="open_draft_pr", risk=ToolRisk.IRREVERSIBLE),
            _tool(agent="PostureAgent", tool="get_posture_report", risk=ToolRisk.READ),
        ]
        out = compute_ai_activity([], tools, now=NOW, window_days=7)

        calls = out["tool_calls"]
        assert calls["total"] == 4
        assert calls["by_tool"]["open_draft_pr"] == 1
        assert calls["by_agent"] == {"TriageAgent": 3, "PostureAgent": 1}
        assert calls["by_risk_tier"] == {"read": 2, "reversible_write": 1, "irreversible": 1}

    def test_missing_risk_falls_back_to_central_registry(self):
        # ``delete_transaction`` is irreversible in the central registry;
        # an unknown tool defaults to read (the registry's safe default).
        tools = [
            {"agent_type": "X", "tool_name": "delete_transaction", "risk": None},
            {"agent_type": "X", "tool_name": "totally_unknown_tool", "risk": None},
        ]
        out = compute_ai_activity([], tools, now=NOW, window_days=7)
        assert out["tool_calls"]["by_risk_tier"] == {"irreversible": 1, "read": 1}

    def test_empty_is_no_data_not_zero_activity_claim(self):
        out = compute_ai_activity([], [], now=NOW, window_days=7)
        assert out["no_data"] is True
        assert out["runs"]["no_data"] is True
        assert out["tool_calls"]["no_data"] is True

    def test_sample_ids_capped(self):
        runs = [_run(i) for i in range(25)]
        out = compute_ai_activity(runs, [], now=NOW, window_days=7)
        assert len(out["runs"]["sample_run_ids"]) == 10
        assert out["runs"]["total"] == 25


def _agent_row(i, *, capabilities=None, power_flags=None, audit=None):
    return {
        "agent_id": f"agent-{i}",
        "agent_type": "triage_agent",
        "status": "active",
        "capabilities": capabilities if capabilities is not None else {},
        "power_flags": power_flags if power_flags is not None else {},
        "grant_audit_entries": audit or [],
    }


class TestComputeCapabilityGrants:
    def test_enabled_capabilities_extracted_and_counted(self):
        rows = [
            _agent_row(1, capabilities={"open_draft_pr": True}),
            _agent_row(2, capabilities={"open_draft_pr": False}),
        ]
        out = compute_capability_grants(rows, now=NOW)

        assert out["agent_total"] == 2
        assert out["enabled_capability_total"] == 1
        assert out["agents"][0]["enabled_capabilities"] == ["open_draft_pr"]
        assert out["agents"][1]["enabled_capabilities"] == []

    def test_unaudited_grants_flagged_honestly(self):
        entry = {
            "field_name": "capabilities",
            "previous_value": {},
            "new_value": {"open_draft_pr": True},
            "actor_id": "user-1",
            "actor_display": "op",
            "reason": "agent capability toggle via API",
            "created_at": "2026-07-19T10:00:00+00:00",
        }
        rows = [
            _agent_row(1, capabilities={"open_draft_pr": True}, audit=[entry]),
            _agent_row(2, capabilities={"open_draft_pr": True}),
        ]
        out = compute_capability_grants(rows, now=NOW)

        assert out["agents"][0]["grant_history_recorded"] is True
        assert out["agents"][1]["grant_history_recorded"] is False
        assert out["agents_with_grant_history"] == 1
        assert "before it have no recorded history" in out["audit_note"]

    def test_power_flags_pass_through(self):
        rows = [_agent_row(1, power_flags={"rubric_middleware": True, "approval_granted": False})]
        out = compute_capability_grants(rows, now=NOW)
        assert out["agents"][0]["power_flags"] == {"rubric_middleware": True, "approval_granted": False}

    def test_empty_is_no_data(self):
        out = compute_capability_grants([], now=NOW)
        assert out["no_data"] is True
        assert out["agents"] == []


def _pr(i, opened_at):
    return {
        "task_id": f"task-{i}",
        "title": f"finding {i}",
        "url": f"https://github.com/o/r/pull/{i}",
        "repo": "o/r",
        "branch": f"autosec/finding-{i}",
        "opened_by": "user-1",
        "opened_at": opened_at,
    }


class TestComputeHitlLedger:
    def test_window_filter_with_mixed_naive_and_aware_timestamps(self):
        # Naive isoformat (the real metadata shape), aware isoformat, and
        # a datetime object — all inside the window; one aware far outside.
        rows = [
            _pr(1, (NOW - timedelta(days=2)).replace(tzinfo=None).isoformat()),
            _pr(2, (NOW - timedelta(days=3)).isoformat()),
            _pr(3, NOW - timedelta(days=4)),
            _pr(4, (NOW - timedelta(days=90)).isoformat()),
        ]
        out = compute_hitl_ledger(rows, now=NOW, window_days=30)

        assert out["draft_prs_opened"]["count"] == 3
        assert {i["task_id"] for i in out["draft_prs_opened"]["items"]} == {"task-1", "task-2", "task-3"}
        assert out["approvals"]["granted"] == 3

    def test_denials_reported_as_not_recorded_never_zero(self):
        out = compute_hitl_ledger([_pr(1, NOW.isoformat())], now=NOW, window_days=30)
        assert out["approvals"]["denials_recorded"] is False
        assert out["approvals"]["note"] == APPROVAL_DENIALS_NOTE

    def test_undated_rows_counted_not_silently_dropped(self):
        out = compute_hitl_ledger([_pr(1, None), _pr(2, "garbage")], now=NOW, window_days=30)
        assert out["draft_prs_opened"]["count"] == 0
        assert out["draft_prs_opened"]["undated_records"] == 2
        # Rows existed, so the top-level aggregate is not "no data".
        assert out["no_data"] is False

    def test_empty_is_no_data(self):
        out = compute_hitl_ledger([], now=NOW, window_days=30)
        assert out["no_data"] is True
        assert out["draft_prs_opened"]["count"] == 0


class TestComputeCredentialInventory:
    def test_reports_presence_and_allowlist_without_secrets(self):
        rows = [
            {
                "id": "conn-1",
                "name": "GitHub",
                "status": "connected",
                "repo_allowlist": ["o/r", "o/other"],
                "has_token": True,
                # Naive + aware mixed — both normalize.
                "created_at": datetime(2026, 7, 1, 9, 0),
                "updated_at": datetime(2026, 7, 19, 9, 0, tzinfo=UTC),
                "last_used_at": None,
            }
        ]
        out = compute_credential_inventory(rows, now=NOW)

        conn = out["github_connections"]["items"][0]
        assert conn["has_token"] is True
        assert conn["repo_allowlist_count"] == 2
        assert conn["created_at"].startswith("2026-07-01")
        assert conn["last_used_at"] is None
        # No token-shaped keys anywhere in the report.
        assert "token_ciphertext" not in str(out)
        assert "secrets_note" in out

    def test_empty_is_no_data(self):
        out = compute_credential_inventory([], now=NOW)
        assert out["no_data"] is True
        assert out["github_connections"]["count"] == 0


class TestComputeKillSwitchStatus:
    def _status(self, **overrides):
        kwargs = {
            "now": NOW,
            "workspace_found": True,
            "ai_teammate_enabled": True,
            "emergency_flag_engaged": False,
            "teammate_profile": {"status": "active", "is_enabled": True},
            "agent_rows": [
                {"agent_id": "a1", "agent_type": "triage_agent", "status": "active"},
                {"agent_id": "a2", "agent_type": "posture_agent", "status": "paused"},
            ],
            "in_flight_deep_runs": 3,
        }
        kwargs.update(overrides)
        return compute_kill_switch_status(**kwargs)

    def test_enabled_and_clear_flag_means_not_halted(self):
        out = self._status()
        assert out["ai_halted"] is False
        assert out["ai_teammate_enabled"] is True
        assert out["would_stop"] == {
            "active_agents": 1,
            "in_flight_deep_runs": 3,
            "scheduled_detector_cycles": True,
        }

    def test_workspace_switch_off_halts(self):
        out = self._status(ai_teammate_enabled=False)
        assert out["ai_halted"] is True
        assert out["would_stop"]["scheduled_detector_cycles"] is False

    def test_emergency_flag_halts_even_when_switch_on(self):
        out = self._status(emergency_flag_engaged=True)
        assert out["ai_halted"] is True
        assert out["emergency_flag_engaged"] is True

    def test_agent_rows_bucketed_by_status(self):
        out = self._status()
        assert out["agents"]["by_status"] == {"active": 1, "paused": 1}
        assert out["agents"]["total"] == 2

    def test_missing_workspace_is_no_data(self):
        out = self._status(workspace_found=False, ai_teammate_enabled=False, teammate_profile=None, agent_rows=[])
        assert out["no_data"] is True
        assert out["workspace_found"] is False
