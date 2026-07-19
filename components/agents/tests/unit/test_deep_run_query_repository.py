"""Unit tests for the deep-run query repository's pure-logic helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any

from components.agents.infrastructure.repositories.orm_deep_run_query_repository import (
    _completed_count,
    _progress_percent,
    _subagent_views,
    _task_count,
)


@dataclass
class _FakeLog:
    """Test double for ``DeepRunLog`` — only the fields the rollup reads."""
    id: int
    created_at: datetime
    event_type: str
    status: str = ""
    agent_type: str = ""
    tool_name: str = ""
    payload: dict[str, Any] = None


def _now():
    return datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


class TestProgressMath:
    def test_empty_state_is_zero(self):
        assert _progress_percent({}) == 0

    def test_non_dict_state_is_zero(self):
        assert _progress_percent(None) == 0
        assert _progress_percent("not a dict") == 0

    def test_zero_tasks_is_zero(self):
        assert _progress_percent({"plan": {"tasks": []}}) == 0

    def test_all_done_is_100(self):
        state = {
            "plan": {"tasks": [{"id": "a"}, {"id": "b"}]},
            "completed_tasks": [{"id": "a"}, {"id": "b"}],
        }
        assert _progress_percent(state) == 100

    def test_half_done_is_50(self):
        state = {
            "plan": {"tasks": [{"id": "a"}, {"id": "b"}]},
            "completed_tasks": [{"id": "a"}],
        }
        assert _progress_percent(state) == 50

    def test_overcounted_caps_at_100(self):
        state = {
            "plan": {"tasks": [{"id": "a"}]},
            "completed_tasks": [{"id": "a"}, {"id": "a"}],
        }
        assert _progress_percent(state) == 100

    def test_task_count_and_completed_count_agree(self):
        state = {
            "plan": {"tasks": [1, 2, 3, 4]},
            "completed_tasks": [1, 2],
        }
        assert _task_count(state) == 4
        assert _completed_count(state) == 2


class TestSubagentRollup:
    def test_no_events_returns_empty(self):
        assert _subagent_views([]) == ()

    def test_single_running_worker(self):
        t0 = _now()
        logs = [
            _FakeLog(
                id=1, created_at=t0, event_type="worker_started",
                agent_type="workspace_agent", payload={"task_id": "t-1"},
            ),
        ]
        views = _subagent_views(logs)
        assert len(views) == 1
        assert views[0].task_id == "t-1"
        assert views[0].status == "running"
        assert views[0].started_at == t0
        assert views[0].completed_at is None

    def test_worker_completion_sets_completed_at_and_status(self):
        t0 = _now()
        t1 = t0 + timedelta(seconds=3)
        logs = [
            _FakeLog(id=1, created_at=t0, event_type="worker_started",
                     agent_type="workspace_agent", payload={"task_id": "t-1"}),
            _FakeLog(id=2, created_at=t1, event_type="worker_completed",
                     payload={"task_id": "t-1"}),
        ]
        view = _subagent_views(logs)[0]
        assert view.status == "completed"
        assert view.started_at == t0
        assert view.completed_at == t1

    def test_worker_failure_status(self):
        t0 = _now()
        logs = [
            _FakeLog(id=1, created_at=t0, event_type="worker_started",
                     agent_type="x", payload={"task_id": "t-1"}),
            _FakeLog(id=2, created_at=t0 + timedelta(seconds=1),
                     event_type="worker_failed", payload={"task_id": "t-1"}),
        ]
        assert _subagent_views(logs)[0].status == "failed"

    def test_worker_blocked_status(self):
        t0 = _now()
        logs = [
            _FakeLog(id=1, created_at=t0, event_type="worker_started",
                     agent_type="x", payload={"task_id": "t-1"}),
            _FakeLog(id=2, created_at=t0 + timedelta(seconds=1),
                     event_type="worker_blocked", status="denied", payload={"task_id": "t-1"}),
        ]
        assert _subagent_views(logs)[0].status == "blocked"

    def test_tool_calls_grouped_under_task(self):
        t0 = _now()
        logs = [
            _FakeLog(id=1, created_at=t0, event_type="worker_started",
                     agent_type="workspace_agent", payload={"task_id": "t-1"}),
            _FakeLog(id=2, created_at=t0 + timedelta(seconds=1),
                     event_type="tool_call", tool_name="retrieve_workspace_context",
                     agent_type="workspace_agent", payload={"task_id": "t-1"}),
            _FakeLog(id=3, created_at=t0 + timedelta(seconds=2),
                     event_type="tool_call", tool_name="get_organization_info",
                     agent_type="workspace_agent", payload={"task_id": "t-1"}),
            _FakeLog(id=4, created_at=t0 + timedelta(seconds=3),
                     event_type="worker_completed", payload={"task_id": "t-1"}),
        ]
        view = _subagent_views(logs)[0]
        tool_names = [c["tool_name"] for c in view.tool_calls]
        assert tool_names == ["retrieve_workspace_context", "get_organization_info"]

    def test_multiple_tasks_are_distinct(self):
        t0 = _now()
        logs = [
            _FakeLog(id=1, created_at=t0, event_type="worker_started",
                     agent_type="a", payload={"task_id": "t-1"}),
            _FakeLog(id=2, created_at=t0 + timedelta(seconds=1),
                     event_type="worker_completed", payload={"task_id": "t-1"}),
            _FakeLog(id=3, created_at=t0 + timedelta(seconds=2),
                     event_type="worker_started", agent_type="b",
                     payload={"task_id": "t-2"}),
        ]
        views = _subagent_views(logs)
        assert [v.task_id for v in views] == ["t-1", "t-2"]
        assert views[0].status == "completed"
        assert views[1].status == "running"
