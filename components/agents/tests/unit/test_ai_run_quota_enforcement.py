"""Metered-AI enforcement at the application-service chokepoint (P3).

Pure unit test: a fake ``AiRunQuotaPort`` + fake provider prove that

* ``execute_agent`` / ``deep_plan_and_run`` / ``deep_run_plan`` check the
  quota, raise ``AiRunLimitExceeded`` when over, and record a run only
  after the underlying call succeeds;
* ``agent_chat`` never touches the quota at all (chat stays free) — proven
  by wiring a quota fake that explodes if any method is called.
"""
from __future__ import annotations

import pytest

from components.agents.application.ports.ai_run_quota_port import AiRunQuotaStatus
from components.agents.application.service import AgentsService
from components.agents.domain.errors import AiRunLimitExceeded


class _Command:
    def __init__(self, *, workspace_id=None, agent_id=None):
        self.workspace_id = workspace_id
        self.agent_id = agent_id


class _RecordingQuota:
    def __init__(self, status):
        self._status = status
        self.checks = []
        self.recorded = []

    def check_for_workspace(self, workspace_id):
        self.checks.append(("workspace", workspace_id))
        return self._status

    def check_for_agent(self, agent_id):
        self.checks.append(("agent", agent_id))
        return self._status

    def record_run(self, workspace_id):
        self.recorded.append(workspace_id)


class _ExplodingQuota:
    """Any access is a test failure — proves chat never meters."""

    def _boom(self, *a, **k):  # noqa: ANN001
        raise AssertionError("chat must not touch the AI-run quota")

    check_for_workspace = _boom
    check_for_agent = _boom
    record_run = _boom


class _Recorder:
    def __init__(self, result="RAN"):
        self.result = result
        self.calls = 0

    def execute(self, command):  # use-case shape
        self.calls += 1
        return self.result

    def dispatch(self, command):  # command-bus shape
        self.calls += 1
        return self.result


class _FakeProvider:
    def __init__(self, *, quota, runner=None, chat=None):
        self._quota = quota
        self._runner = runner or _Recorder()
        self._chat = chat or _Recorder("CHATTED")

    def build_ai_run_quota(self):
        return self._quota

    def build_execute_agent_use_case(self):
        return self._runner

    def build_command_bus(self):
        return self._runner

    def build_agent_chat_use_case(self):
        return self._chat


def _allowed(ws="ws-1"):
    return AiRunQuotaStatus(allowed=True, used=0, limit=20, workspace_id=ws)


def _over(ws="ws-1"):
    return AiRunQuotaStatus(allowed=False, used=20, limit=20, workspace_id=ws)


class TestExecuteAgentMetering:
    def test_under_limit_runs_then_records(self):
        quota = _RecordingQuota(_allowed("ws-1"))
        runner = _Recorder("EXECUTED")
        svc = AgentsService(provider=_FakeProvider(quota=quota, runner=runner))

        result = svc.execute_agent(_Command(agent_id="agent-1"))

        assert result == "EXECUTED"
        assert quota.checks == [("agent", "agent-1")]
        assert quota.recorded == ["ws-1"]
        assert runner.calls == 1

    def test_over_limit_raises_and_does_not_run_or_record(self):
        quota = _RecordingQuota(_over("ws-1"))
        runner = _Recorder()
        svc = AgentsService(provider=_FakeProvider(quota=quota, runner=runner))

        with pytest.raises(AiRunLimitExceeded) as exc:
            svc.execute_agent(_Command(agent_id="agent-1"))

        assert exc.value.used == 20 and exc.value.limit == 20
        assert runner.calls == 0
        assert quota.recorded == []


class TestDeepRunMetering:
    def test_deep_plan_and_run_under_limit_runs_then_records(self):
        quota = _RecordingQuota(_allowed("ws-9"))
        bus = _Recorder("DEEP")
        svc = AgentsService(provider=_FakeProvider(quota=quota, runner=bus))

        result = svc.deep_plan_and_run(_Command(workspace_id="ws-9"))

        assert result == "DEEP"
        assert quota.checks == [("workspace", "ws-9")]
        assert quota.recorded == ["ws-9"]

    def test_deep_plan_and_run_over_limit_raises(self):
        quota = _RecordingQuota(_over("ws-9"))
        bus = _Recorder()
        svc = AgentsService(provider=_FakeProvider(quota=quota, runner=bus))

        with pytest.raises(AiRunLimitExceeded):
            svc.deep_plan_and_run(_Command(workspace_id="ws-9"))
        assert bus.calls == 0
        assert quota.recorded == []

    def test_deep_run_plan_accepts_validated_plan_kwarg_and_meters(self):
        quota = _RecordingQuota(_allowed("ws-2"))
        bus = _Recorder("PLANNED")
        svc = AgentsService(provider=_FakeProvider(quota=quota, runner=bus))

        # The controller passes validated_plan=… — the method must absorb it.
        result = svc.deep_run_plan(_Command(workspace_id="ws-2"), validated_plan=object())

        assert result == "PLANNED"
        assert quota.recorded == ["ws-2"]


class TestChatIsFree:
    def test_agent_chat_never_touches_quota(self):
        # Even with an exploding quota, chat must succeed untouched.
        svc = AgentsService(
            provider=_FakeProvider(quota=_ExplodingQuota(), chat=_Recorder("CHATTED"))
        )

        result = svc.agent_chat(_Command(workspace_id="ws-1"))

        assert result == "CHATTED"
