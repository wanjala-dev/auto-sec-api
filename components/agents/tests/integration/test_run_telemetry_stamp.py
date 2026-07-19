"""Telemetry stamp lands on the finding row post-dispatch (task #58).

Real DB; the deep-run execute path is FAKED at the cycle's delegator boundary
(``_delegate_to_agent``) — the fake plays the specialist's part (triage-stamps
the finding under the same metadata discipline the real tools use) and returns
a deep-shaped result whose ``final_output.run_metadata`` carries the run
telemetry. Pins:

* ``dispatch_finding_specialist`` stamps ``metadata.run_telemetry`` on every
  finding the specialist triaged during the dispatch — and ONLY those;
* the stamp carries the A/B slice (rubric verdict, retries, budget outcome,
  source_thread_id) next to the existing triage/provenance stamps;
* findings triaged by another specialist, or before the dispatch window, are
  untouched;
* a failed/denied dispatch stamps nothing and still returns cleanly;
* the TaskSerializer surfaces the stamp so the operator sees it on the card.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.utils import timezone

from infrastructure.persistence.project.models import Column, Task


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Suggested", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _finding(workspace, owner, team, column, *, title="[HIGH] celery_worker · ImportError"):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title=title,
        source_type="ai.log_watch",
        metadata={
            "agent_type": "triage_agent",
            "detector": "logwatch.error",
            "triage": {"status": "pending"},
            "payload": {"signal": "ERROR in celery_worker", "lookup_key": "fp1"},
        },
    )


def _triage_stamp(task, *, agent="triage_agent", needs_human=False):
    """Mimic the specialist tools' handled-stamp (same shape as process_pending_finding)."""
    meta = task.metadata or {}
    meta["triage"] = {
        "status": "triaged",
        "agent": agent,
        "triaged_at": timezone.now().isoformat(),
        "actions": ["proposed fix"],
        "suggested": True,
        "needs_human": needs_human,
    }
    task.metadata = meta
    task.save(update_fields=["metadata", "updated_at"])


def _deep_result(*, thread_id="thread-123", rubric_map=None, retries_map=None, budget_reason=None):
    run_metadata = {
        "plan_status": "completed",
        "goal_met": True,
        "rubric_verdicts": rubric_map or {},
    }
    if retries_map:
        run_metadata["worker_retries"] = retries_map
    if budget_reason:
        run_metadata["budget_exceeded_reason"] = budget_reason
    return {
        "success": True,
        "result": "Processed findings.",
        "plan_id": thread_id,
        "thread_id": thread_id,
        "final_output": {"answer": "Processed findings.", "run_metadata": run_metadata},
        "mode": "deep",
    }


def _dispatch(workspace, *, specialist="triage_agent", fake_delegate=None):
    from components.agents.infrastructure.tasks.agent_tasks import dispatch_finding_specialist

    with mock.patch(
        "components.agents.application.services.detector_cycle._delegate_to_agent",
        side_effect=fake_delegate,
    ):
        return dispatch_finding_specialist(
            str(workspace.id), specialist, "Process the pending findings.", {"worker_agent_type": specialist}, None
        )


@pytest.mark.django_db
class TestDispatchStampsTelemetry:
    def test_stamp_lands_on_the_finding_the_specialist_handled(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        finding = _finding(workspace, owner, team, column)

        rubric = {"verdict": "satisfied", "iterations": 2, "grader": "gpt-4o-mini", "source": "rubric_middleware"}

        def fake_delegate(**kwargs):
            _triage_stamp(finding, needs_human=True)
            return _deep_result(
                rubric_map={"plan-task-1": rubric},
                retries_map={"plan-task-1": 1},
                budget_reason="max_cost_usd ($0.50) reached — $0.6100 spent",
            )

        outcome = _dispatch(workspace, fake_delegate=fake_delegate)

        assert outcome["success"] is True
        assert outcome["telemetry_stamped"] == 1
        finding.refresh_from_db()
        telemetry = finding.metadata["run_telemetry"]
        # Single-entry rubric map → run-scoped attribution to this finding.
        assert telemetry["rubric_verdicts"] == {**rubric, "scope": "run"}
        assert telemetry["worker_retries"] == 1
        assert telemetry["budget_exceeded"] == "max_cost_usd ($0.50) reached — $0.6100 spent"
        assert telemetry["source_thread_id"] == "thread-123"
        assert telemetry["specialist"] == "triage_agent"
        assert telemetry["stamped_at"]
        # The triage stamp the specialist wrote is intact next to it.
        assert finding.metadata["triage"]["status"] == "triaged"
        assert finding.metadata["triage"]["needs_human"] is True

    def test_only_this_specialists_fresh_findings_are_stamped(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        mine = _finding(workspace, owner, team, column, title="mine")
        other_agent = _finding(workspace, owner, team, column, title="other agent")
        _triage_stamp(other_agent, agent="optimization_agent")
        stale = _finding(workspace, owner, team, column, title="stale")
        _triage_stamp(stale, agent="triage_agent")
        # Age the stale row OUT of the dispatch window.
        Task.objects.filter(id=stale.id).update(updated_at=timezone.now() - timezone.timedelta(days=1))

        def fake_delegate(**kwargs):
            _triage_stamp(mine)
            return _deep_result()

        outcome = _dispatch(workspace, fake_delegate=fake_delegate)

        assert outcome["telemetry_stamped"] == 1
        mine.refresh_from_db()
        other_agent.refresh_from_db()
        stale.refresh_from_db()
        assert "run_telemetry" in mine.metadata
        assert "run_telemetry" not in other_agent.metadata
        assert "run_telemetry" not in stale.metadata

    def test_failed_dispatch_stamps_nothing_and_returns_cleanly(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        finding = _finding(workspace, owner, team, column)

        def fake_delegate(**kwargs):
            return {"success": False, "code": "agent_not_entitled", "reason": "not enabled"}

        outcome = _dispatch(workspace, fake_delegate=fake_delegate)

        assert outcome["success"] is False
        assert outcome["telemetry_stamped"] == 0
        finding.refresh_from_db()
        assert "run_telemetry" not in finding.metadata

    def test_exact_task_id_match_is_task_scoped(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        finding = _finding(workspace, owner, team, column)
        per_finding_verdict = {"verdict": "failed", "iterations": 2}

        def fake_delegate(**kwargs):
            _triage_stamp(finding)
            # A rubric map keyed by the FINDING id (plus another plan task) —
            # exact attribution must win over the single-entry fallback.
            return _deep_result(
                rubric_map={str(finding.id): per_finding_verdict, "unrelated-plan-task": {"verdict": "satisfied"}}
            )

        _dispatch(workspace, fake_delegate=fake_delegate)

        finding.refresh_from_db()
        assert finding.metadata["run_telemetry"]["rubric_verdicts"] == {**per_finding_verdict, "scope": "task"}


@pytest.mark.django_db
class TestSerializerSurfacesTelemetry:
    def test_task_serializer_exposes_run_telemetry(self, workspace_factory, team_factory):
        from components.project.mappers.rest.project_serializers import TaskSerializer

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        finding = _finding(workspace, owner, team, column)
        _triage_stamp(finding)
        meta = finding.metadata
        meta["run_telemetry"] = {
            "rubric_verdicts": {"verdict": "satisfied", "iterations": 1, "scope": "run"},
            "critic_scores": None,
            "worker_retries": 0,
            "budget_exceeded": None,
            "source_thread_id": "thread-xyz",
            "specialist": "triage_agent",
            "stamped_at": "2026-07-19T00:00:00+00:00",
        }
        finding.metadata = meta
        finding.save(update_fields=["metadata"])

        data = TaskSerializer(finding).data
        assert data["run_telemetry"]["source_thread_id"] == "thread-xyz"
        assert data["run_telemetry"]["rubric_verdicts"]["verdict"] == "satisfied"
        assert data["run_telemetry"]["specialist"] == "triage_agent"

    def test_task_without_stamp_serializes_none(self, workspace_factory, team_factory):
        from components.project.mappers.rest.project_serializers import TaskSerializer

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        finding = _finding(workspace, owner, team, column)
        assert TaskSerializer(finding).data["run_telemetry"] is None
