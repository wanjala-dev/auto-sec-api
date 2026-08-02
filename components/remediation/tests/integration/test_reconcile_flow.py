"""End-to-end reconciler flow over real persistence (ADR 0012 P4a).

Drives ``ReconcileAppliedRemediationsUseCase`` against a real ``project.Task`` with
the merge-check faked (no real GitHub call) and sign-off faked (no ORM in the fork).
Proves the load-bearing contract of Phase 4a:

- a MERGED remediation draft PR → the finding is transitioned to resolved (through
  the project application surface, NOT a cross-context Task write) AND, because the
  gate's three conditions now hold, ONE corpus entry is captured;
- an UNMERGED PR → the finding stays un-resolved and nothing is captured;
- the resolve write goes through ``OrmResolveFindingTaskRepository`` (the owner),
  and re-running is idempotent (no duplicate entry).
"""

from __future__ import annotations

import pytest

from components.project.application.ports.resolve_finding_task_port import ResolveFindingTaskCommand
from components.project.application.providers.project_provider import ProjectProvider
from components.remediation.application.handlers.remediation_capture_handler import (
    capture_remediation_if_gated,
)
from components.remediation.application.providers.remediation_provider import build_remediation_service
from components.remediation.application.use_cases.reconcile_applied_remediations_use_case import (
    ReconcileAppliedRemediationsUseCase,
    RemediationCandidate,
)
from components.remediation.infrastructure.adapters.board_finding_facts_repository import (
    BoardFindingFactsRepository,
)
from components.remediation.infrastructure.repositories.remediation_entry_repository import (
    DjangoRemediationEntryRepository,
)
from components.remediation.tests.unit.fakes import FakeSignOffGate

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_PR_URL = "https://github.com/acme/repo/pull/7"


def _board(workspace_factory, team_factory):
    from infrastructure.persistence.project.models import Column

    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _finding_task(workspace, owner, team, column):
    """A triaged log-watch finding carrying an OPEN draft PR — not yet resolved."""
    from infrastructure.persistence.project.models import Task

    metadata = {
        "provenance": {
            "events": [
                {"actor": "detector:logwatch", "action": "filed finding", "at": "t0"},
                {"actor": "agent:triage_agent via user:u1", "action": "opened draft PR", "at": "t1"},
            ]
        },
        "triage": {"status": "triaged"},
        "payload": {
            "fingerprint": "fp-abc",
            "draft_pr": {"url": _PR_URL, "repo": "acme/repo", "branch": "fix/x"},
            "suggested_fix": "rename the class alias",
            "sign_off": {"artifact_type": "remediation", "artifact_id": "signoff-1"},
        },
    }
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="[FINDING] casing ImportError",
        source_type="ai.log_watch",
        metadata=metadata,
    )


def _wire(*, merged: bool, approved: bool):
    """Reconciler with faked merge-check + faked sign-off; real resolve + real capture."""
    resolve_uc = ProjectProvider.build_resolve_finding_task_use_case()
    service = build_remediation_service(
        store=DjangoRemediationEntryRepository(),
        sign_off_gate=FakeSignOffGate(approved=approved),
        finding_facts=BoardFindingFactsRepository(),
    )

    def check_merged(ws_id, pr_url):
        return merged

    def resolve_finding(ws_id, task_id, reason, resolved_by):
        result = resolve_uc.execute(
            command=ResolveFindingTaskCommand(
                workspace_id=str(ws_id), task_id=task_id, reason=reason, resolved_by=resolved_by
            )
        )
        # Mirror the task wiring: report only a NEW transition (an already-resolved
        # finding is a no-op the counter should not re-count).
        return bool(result.resolved and not result.already_resolved)

    def capture(**kwargs):
        return capture_remediation_if_gated(service=service, **kwargs)

    return ReconcileAppliedRemediationsUseCase(
        check_merged=check_merged, resolve_finding=resolve_finding, capture=capture
    )


def _candidate(workspace, task):
    return RemediationCandidate(
        workspace_id=workspace.id,
        finding_task_id=str(task.id),
        draft_pr_url=_PR_URL,
        sign_off_artifact_type="remediation",
        sign_off_artifact_id="signoff-1",
        code="rename the alias",
        language="python",
        title="Fix casing import",
    )


class TestMergedResolvesAndCaptures:
    def test_merged_pr_resolves_finding_and_captures_entry(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        result = _wire(merged=True, approved=True).execute([_candidate(ws, task)])

        assert result.merged == 1
        assert result.resolved == 1
        assert result.captured == 1

        # The finding was transitioned to resolved on the OWNED Task (via project).
        task.refresh_from_db()
        assert task.metadata["triage"]["status"] == "resolved"
        assert task.metadata["payload"]["resolved"] is True

        # Exactly one corpus entry was admitted, linked to the finding, raw code.
        rows = list(Row.active.filter(workspace_id=ws.id))
        assert len(rows) == 1
        assert rows[0].finding_task_id == str(task.id)
        assert rows[0].applied_pr_url == _PR_URL
        assert rows[0].code == "rename the alias"

    def test_rerun_is_idempotent(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)
        reconciler = _wire(merged=True, approved=True)

        reconciler.execute([_candidate(ws, task)])
        # Second pass: finding already resolved, entry already captured → no dupes.
        second = reconciler.execute([_candidate(ws, task)])

        assert Row.active.filter(workspace_id=ws.id).count() == 1
        assert second.captured == 1  # idempotent hit returns the existing entry
        assert second.resolved == 0  # already resolved → the project surface no-ops


class TestUnmergedDoesNothing:
    def test_unmerged_pr_neither_resolves_nor_captures(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        result = _wire(merged=False, approved=True).execute([_candidate(ws, task)])

        assert result.merged == 0
        assert result.skipped_unmerged == 1
        task.refresh_from_db()
        assert task.metadata["triage"]["status"] == "triaged"  # untouched
        assert Row.objects.filter(workspace_id=ws.id).count() == 0


class TestGateRefusalStillResolves:
    def test_merged_but_not_approved_resolves_but_refuses_entry(self, workspace_factory, team_factory):
        # The merge is real, so the finding resolves; but sign-off isn't approved, so
        # the gate REFUSES the corpus entry (resolution and admission are separate).
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        result = _wire(merged=True, approved=False).execute([_candidate(ws, task)])

        assert result.resolved == 1
        assert result.captured == 0
        assert result.gate_refused == 1
        task.refresh_from_db()
        assert task.metadata["triage"]["status"] == "resolved"  # still resolved
        assert Row.objects.filter(workspace_id=ws.id).count() == 0  # but nothing admitted
