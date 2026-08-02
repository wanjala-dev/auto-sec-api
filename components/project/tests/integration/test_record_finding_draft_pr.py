"""Integration tests: the owning-context draft-PR recorder use case.

The ``project`` context owns the board ``Task``, so it owns the write that stamps
a draft PR onto a finding (architecture-skill C2). This use case is what the
integrations VCS capability now delegates to (via ``RecordFindingDraftPrPort``)
instead of writing ``project``'s ORM directly. These tests pin the contract the
old inline ``open_draft_pr_use_case._record_on_finding`` had:

* the ``metadata.payload.draft_pr`` shape + provenance event + card comment;
* idempotency under concurrency (an already-recorded draft PR is left untouched);
* a deleted task is a silent no-op (never raises).
"""

from __future__ import annotations

import pytest

from components.project.application.ports.record_finding_draft_pr_port import (
    RecordFindingDraftPrCommand,
)
from components.project.application.providers.project_provider import ProjectProvider


def _board(workspace_factory, team_factory):
    from infrastructure.persistence.project.models import Column

    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _finding(workspace, owner, team, column, *, extra_payload=None):
    from infrastructure.persistence.project.models import Task

    payload = {"service": "celery_worker", "severity": "high"}
    payload.update(extra_payload or {})
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="[HIGH] celery_worker · ImportError",
        source_type="ai.log_watch",
        metadata={
            "provenance": {"events": [{"actor": "detector:logwatch.error", "action": "filed", "at": "t0"}]},
            "triage": {"status": "triaged"},
            "payload": payload,
        },
    )


def _cmd(workspace, task, owner, **overrides):
    base = {
        "workspace_id": str(workspace.id),
        "task_id": str(task.id),
        "performed_by": str(owner.id),
        "acting_agent": "triage_agent",
        "pr_url": "https://github.com/wanjala-dev/auto-sec-api/pull/7",
        "pr_repo": "wanjala-dev/auto-sec-api",
        "branch": f"autosec/finding-{task.id}",
    }
    base.update(overrides)
    return RecordFindingDraftPrCommand(**base)


@pytest.mark.django_db
class TestRecordFindingDraftPr:
    def test_records_draft_pr_provenance_and_comment(self, workspace_factory, team_factory):
        from infrastructure.persistence.project.models import TaskComment

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column)

        use_case = ProjectProvider.build_record_finding_draft_pr_use_case()
        result = use_case.execute(command=_cmd(workspace, task, owner))

        assert result.recorded is True
        task.refresh_from_db()
        draft = task.metadata["payload"]["draft_pr"]
        assert draft["url"] == "https://github.com/wanjala-dev/auto-sec-api/pull/7"
        assert draft["repo"] == "wanjala-dev/auto-sec-api"
        assert draft["branch"] == f"autosec/finding-{task.id}"
        assert draft["opened_by"] == str(owner.id)
        assert draft["opened_at"]

        events = task.metadata["provenance"]["events"]
        assert events[-1]["actor"] == f"agent:triage_agent via user:{owner.id}"
        assert draft["url"] in events[-1]["action"]
        assert task.metadata["provenance"]["last_handled_by"] == "triage_agent"

        comment = TaskComment.objects.filter(task=task).first()
        assert comment is not None
        assert draft["url"] in comment.comment

    def test_idempotent_when_draft_pr_already_recorded(self, workspace_factory, team_factory):
        from infrastructure.persistence.project.models import TaskComment

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        existing = {
            "url": "https://github.com/wanjala-dev/auto-sec-api/pull/3",
            "repo": "wanjala-dev/auto-sec-api",
            "branch": "autosec/finding-old",
            "opened_by": str(owner.id),
            "opened_at": "2026-07-18T00:00:00+00:00",
        }
        task = _finding(workspace, owner, team, column, extra_payload={"draft_pr": existing})

        use_case = ProjectProvider.build_record_finding_draft_pr_use_case()
        result = use_case.execute(command=_cmd(workspace, task, owner))

        assert result.recorded is False
        task.refresh_from_db()
        # The first PR's record is preserved; no second event or comment.
        assert task.metadata["payload"]["draft_pr"] == existing
        assert TaskComment.objects.filter(task=task).count() == 0

    def test_deleted_task_is_a_silent_noop(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column)
        task_id = str(task.id)
        task.delete()

        use_case = ProjectProvider.build_record_finding_draft_pr_use_case()
        result = use_case.execute(command=_cmd(workspace, task, owner, task_id=task_id))

        assert result.recorded is False

    def test_missing_author_still_records_metadata(self, workspace_factory, team_factory):
        from infrastructure.persistence.project.models import TaskComment

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column)

        use_case = ProjectProvider.build_record_finding_draft_pr_use_case()
        # A performed_by that resolves to no user → metadata still written, comment skipped.
        result = use_case.execute(
            command=_cmd(workspace, task, owner, performed_by="00000000-0000-0000-0000-000000000000")
        )

        assert result.recorded is True
        task.refresh_from_db()
        assert task.metadata["payload"]["draft_pr"]["url"].endswith("/pull/7")
        assert TaskComment.objects.filter(task=task).count() == 0
