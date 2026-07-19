"""Integration tests for firing due recurring workflow schedules.

Covers: a due schedule creates runs for its saved audience and advances
next_run_at; not-due / disabled schedules are skipped; refiring the same slot
is idempotent (no duplicate runs); a non-published workflow advances without
creating runs.
"""

from __future__ import annotations

import uuid
from datetime import time, timedelta

import pytest
from django.utils import timezone

from components.workflow.application.service import WorkflowService
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowSchedule,
)

pytestmark = pytest.mark.django_db


def _graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "end", "type": "end", "label": "End"},
        ],
        "edges": [{"id": "start-end", "from": "start", "to": "end"}],
    }


def _workflow(workspace, status=Workflow.Status.PUBLISHED):
    return Workflow.objects.create(
        workspace=workspace,
        name="Scheduled flow",
        goal="campaign",
        status=status,
        version=1,
        graph=_graph(),
    )


def _schedule(workflow, workspace, *, due_at, audience, enabled=True):
    return WorkflowSchedule.objects.create(
        workflow=workflow,
        workspace=workspace,
        cadence=WorkflowSchedule.Cadence.DAILY,
        run_time=time(9, 0),
        timezone="UTC",
        audience=audience,
        enabled=enabled,
        next_run_at=due_at,
    )


def _audience():
    return [{"target_type": "contact", "target_id": str(uuid.uuid4())}]


class TestFireDueSchedules:
    def test_due_schedule_creates_runs_and_advances(self, workspace_factory):
        ws = workspace_factory()
        wf = _workflow(ws)
        audience = _audience()
        sched = _schedule(
            wf, ws, due_at=timezone.now() - timedelta(minutes=1), audience=audience
        )

        now = timezone.now()
        result = WorkflowService().fire_due_schedules(now)

        assert result == {"due": 1, "fired": 1}
        assert (
            WorkflowRun.objects.filter(
                workflow=wf, target_id=audience[0]["target_id"]
            ).count()
            == 1
        )
        sched.refresh_from_db()
        assert sched.last_run_at is not None
        assert sched.next_run_at > now

    def test_not_due_schedule_is_skipped(self, workspace_factory):
        ws = workspace_factory()
        wf = _workflow(ws)
        _schedule(
            wf, ws, due_at=timezone.now() + timedelta(hours=2), audience=_audience()
        )

        result = WorkflowService().fire_due_schedules(timezone.now())

        assert result["due"] == 0
        assert WorkflowRun.objects.filter(workflow=wf).count() == 0

    def test_disabled_schedule_not_fired(self, workspace_factory):
        ws = workspace_factory()
        wf = _workflow(ws)
        _schedule(
            wf,
            ws,
            due_at=timezone.now() - timedelta(minutes=1),
            audience=_audience(),
            enabled=False,
        )

        result = WorkflowService().fire_due_schedules(timezone.now())

        assert result["due"] == 0
        assert WorkflowRun.objects.filter(workflow=wf).count() == 0

    def test_refiring_same_slot_is_idempotent(self, workspace_factory):
        ws = workspace_factory()
        wf = _workflow(ws)
        audience = _audience()
        original_slot = timezone.now() - timedelta(minutes=1)
        sched = _schedule(wf, ws, due_at=original_slot, audience=audience)

        WorkflowService().fire_due_schedules(timezone.now())
        # Force the same slot to look due again — the per-fire idempotency key
        # (schedule:<id>:<slot>) must prevent a duplicate run.
        sched.refresh_from_db()
        sched.next_run_at = original_slot
        sched.save(update_fields=["next_run_at"])
        WorkflowService().fire_due_schedules(timezone.now())

        assert (
            WorkflowRun.objects.filter(
                workflow=wf, target_id=audience[0]["target_id"]
            ).count()
            == 1
        )

    def test_unpublished_workflow_advances_without_runs(self, workspace_factory):
        ws = workspace_factory()
        wf = _workflow(ws, status=Workflow.Status.DRAFT)
        sched = _schedule(
            wf, ws, due_at=timezone.now() - timedelta(minutes=1), audience=_audience()
        )

        now = timezone.now()
        result = WorkflowService().fire_due_schedules(now)

        assert result["fired"] == 1
        assert WorkflowRun.objects.filter(workflow=wf).count() == 0
        sched.refresh_from_db()
        assert sched.next_run_at > now
