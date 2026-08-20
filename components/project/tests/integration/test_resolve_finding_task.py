"""Integration tests for the finding-resolve application surface (ADR 0012 P4a).

The project context owns the board Task, so it owns the finding-resolved
transition. Proves: the resolved marker + provenance are written, it is idempotent,
and a task from another workspace is never touched (tenant isolation).
"""

from __future__ import annotations

import pytest

from components.project.application.ports.resolve_finding_task_port import ResolveFindingTaskCommand
from components.project.application.providers.project_provider import ProjectProvider

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _finding_task(workspace_factory, team_factory, *, resolved: bool = False):
    from infrastructure.persistence.project.models import Column, Task

    ws = workspace_factory()
    owner = ws.workspace_owner
    team = team_factory(workspace=ws, created_by=owner, members=[owner])
    column = Column.objects.create(team=team, workspace=ws, project=None, title="Backlog", order=0, created_by=owner)
    task = Task.objects.create(
        team=team,
        workspace=ws,
        column=column,
        created_by=owner,
        title="[FINDING] casing ImportError",
        source_type="ai.log_watch",
        metadata={"triage": {"status": "resolved" if resolved else "triaged"}, "payload": {"lookup_key": "fp"}},
    )
    return ws, task


def _resolve(ws, task_id, **kw):
    uc = ProjectProvider.build_resolve_finding_task_use_case()
    return uc.execute(command=ResolveFindingTaskCommand(workspace_id=str(ws.id), task_id=str(task_id), **kw))


class TestResolve:
    def test_marks_resolved_and_stamps_provenance(self, workspace_factory, team_factory):

        ws, task = _finding_task(workspace_factory, team_factory)
        result = _resolve(ws, task.id, reason="remediated", resolved_by="system:test")

        assert result.found is True and result.resolved is True and result.already_resolved is False
        task.refresh_from_db()
        assert task.metadata["triage"]["status"] == "resolved"
        assert task.metadata["triage"]["resolved_reason"] == "remediated"
        assert task.metadata["payload"]["resolved"] is True
        events = task.metadata["provenance"]["events"]
        assert events[-1]["actor"] == "system:test"
        assert "resolved finding" in events[-1]["action"]

    def test_idempotent_on_already_resolved(self, workspace_factory, team_factory):
        ws, task = _finding_task(workspace_factory, team_factory, resolved=True)
        result = _resolve(ws, task.id)
        assert result.resolved is True and result.already_resolved is True

    def test_absent_task_is_not_found(self, workspace_factory, team_factory):
        ws, _ = _finding_task(workspace_factory, team_factory)
        result = _resolve(ws, 999_999)
        assert result.found is False and result.resolved is False


class TestTenantIsolation:
    def test_other_workspace_task_is_never_resolved(self, workspace_factory, team_factory):

        ws_a, task_a = _finding_task(workspace_factory, team_factory)
        ws_b = workspace_factory()

        # Ask to resolve task_a under workspace B's id → found=False, task untouched.
        result = _resolve(ws_b, task_a.id)
        assert result.found is False
        task_a.refresh_from_db()
        assert task_a.metadata["triage"]["status"] == "triaged"
