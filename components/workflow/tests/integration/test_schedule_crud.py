"""Integration tests for schedule CRUD (service + serializer).

Mirrors the workflow context's convention of exercising the application service
and serializers directly rather than the HTTP client.
"""

from __future__ import annotations

from datetime import time

import pytest
from django.utils import timezone

from components.workflow.application.service import WorkflowService
from components.workflow.mappers.rest.workflow_serializers import (
    WorkflowScheduleSerializer,
)
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowSchedule,
)

pytestmark = pytest.mark.django_db


def _workflow(workspace):
    return Workflow.objects.create(
        workspace=workspace,
        name="Flow",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph={"nodes": [], "edges": []},
    )


class TestScheduleCrud:
    def test_create_sets_next_run_at(self, workspace_factory):
        wf = _workflow(workspace_factory())
        schedule = WorkflowService().create_schedule(
            workflow=wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.DAILY,
            run_time=time(9, 0),
            timezone="UTC",
            audience=[{"target_type": "contact", "target_id": "x"}],
        )
        assert schedule.id is not None
        assert schedule.next_run_at is not None
        assert str(schedule.workspace_id) == str(wf.workspace_id)

    def test_list_returns_workflow_schedules(self, workspace_factory):
        wf = _workflow(workspace_factory())
        svc = WorkflowService()
        svc.create_schedule(
            workflow=wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.DAILY,
            run_time=time(9, 0),
        )
        assert svc.list_schedules(str(wf.id)).count() == 1

    def test_update_recomputes_next_run_on_timing_change(self, workspace_factory):
        wf = _workflow(workspace_factory())
        svc = WorkflowService()
        schedule = svc.create_schedule(
            workflow=wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.DAILY,
            run_time=time(9, 0),
        )
        before = schedule.next_run_at
        updated = svc.update_schedule(
            schedule, timezone.now(), run_time=time(18, 30)
        )
        assert updated.run_time == time(18, 30)
        assert updated.next_run_at != before

    def test_update_disable_does_not_touch_next_run(self, workspace_factory):
        wf = _workflow(workspace_factory())
        svc = WorkflowService()
        schedule = svc.create_schedule(
            workflow=wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.DAILY,
            run_time=time(9, 0),
        )
        before = schedule.next_run_at
        updated = svc.update_schedule(schedule, timezone.now(), enabled=False)
        assert updated.enabled is False
        assert updated.next_run_at == before

    def test_delete_removes_schedule(self, workspace_factory):
        wf = _workflow(workspace_factory())
        svc = WorkflowService()
        schedule = svc.create_schedule(
            workflow=wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.DAILY,
            run_time=time(9, 0),
        )
        assert svc.delete_schedule(str(schedule.id)) == 1
        assert svc.get_schedule(str(schedule.id)) is None

    def test_create_interval_schedule_has_no_run_time(self, workspace_factory):
        wf = _workflow(workspace_factory())
        schedule = WorkflowService().create_schedule(
            workflow=wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.INTERVAL,
            interval_minutes=360,  # every 6 hours
            audience=[{"target_type": "contact", "target_id": "x"}],
        )
        assert schedule.run_time is None
        assert schedule.interval_minutes == 360
        assert schedule.next_run_at is not None


class TestScheduledListAnnotation:
    def test_next_run_annotated_and_scheduled_filter(self, workspace_factory):
        ws = workspace_factory()
        scheduled_wf = _workflow(ws)
        _workflow(ws)  # second workflow with no schedule
        svc = WorkflowService()
        svc.create_schedule(
            workflow=scheduled_wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.INTERVAL,
            interval_minutes=360,
        )

        all_wfs = list(svc.get_workflows(workspace_id=str(ws.id)))
        next_runs = {str(w.id): w.next_run_at for w in all_wfs}
        assert next_runs[str(scheduled_wf.id)] is not None
        assert len(all_wfs) == 2

        scheduled_only = list(
            svc.get_workflows(workspace_id=str(ws.id), scheduled=True)
        )
        assert [str(w.id) for w in scheduled_only] == [str(scheduled_wf.id)]

    def test_disabled_schedule_not_counted_as_scheduled(self, workspace_factory):
        ws = workspace_factory()
        wf = _workflow(ws)
        svc = WorkflowService()
        schedule = svc.create_schedule(
            workflow=wf,
            now=timezone.now(),
            cadence=WorkflowSchedule.Cadence.DAILY,
            run_time=time(9, 0),
        )
        svc.update_schedule(schedule, timezone.now(), enabled=False)
        assert list(svc.get_workflows(workspace_id=str(ws.id), scheduled=True)) == []


class TestScheduleSerializerValidation:
    def test_weekly_requires_days(self):
        s = WorkflowScheduleSerializer(
            data={"cadence": "weekly", "run_time": "09:00", "days_of_week": []}
        )
        assert not s.is_valid()
        assert "days_of_week" in s.errors

    def test_monthly_requires_day_of_month(self):
        s = WorkflowScheduleSerializer(
            data={"cadence": "monthly", "run_time": "09:00"}
        )
        assert not s.is_valid()
        assert "day_of_month" in s.errors

    def test_day_of_month_capped_at_28(self):
        s = WorkflowScheduleSerializer(
            data={"cadence": "monthly", "run_time": "09:00", "day_of_month": 31}
        )
        assert not s.is_valid()
        assert "day_of_month" in s.errors

    def test_valid_daily(self):
        s = WorkflowScheduleSerializer(
            data={
                "cadence": "daily",
                "run_time": "09:00",
                "audience": [{"target_type": "contact", "target_id": "x"}],
            }
        )
        assert s.is_valid(), s.errors

    def test_bad_audience_rejected(self):
        s = WorkflowScheduleSerializer(
            data={
                "cadence": "daily",
                "run_time": "09:00",
                "audience": [{"target_type": "contact"}],  # missing target_id
            }
        )
        assert not s.is_valid()
        assert "audience" in s.errors

    def test_interval_requires_interval_minutes(self):
        s = WorkflowScheduleSerializer(data={"cadence": "interval"})
        assert not s.is_valid()
        assert "interval_minutes" in s.errors

    def test_interval_below_floor_rejected(self):
        s = WorkflowScheduleSerializer(
            data={"cadence": "interval", "interval_minutes": 5}
        )
        assert not s.is_valid()
        assert "interval_minutes" in s.errors

    def test_valid_interval_needs_no_run_time(self):
        s = WorkflowScheduleSerializer(
            data={
                "cadence": "interval",
                "interval_minutes": 360,
                "audience": [{"target_type": "contact", "target_id": "x"}],
            }
        )
        assert s.is_valid(), s.errors
