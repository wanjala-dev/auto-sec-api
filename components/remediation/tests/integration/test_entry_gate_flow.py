"""End-to-end entry-gate over the real repository + real board-facts adapter.

Proves the D1 gate against the persistence layer and a real ``project.Task``:
the gate admits only when all three conditions hold, refuses (writing nothing)
otherwise, links provenance, stores raw code, and never crosses a workspace
boundary. The sign-off signal is faked (sign_off has no ORM to seed and no
adapter registered in the fork) — we assert the gate's *orchestration + tenant
isolation + persistence*, exactly the seam this phase owns.
"""

from __future__ import annotations

import pytest

from components.remediation.application.commands.record_remediation_entry_command import (
    RecordRemediationEntryCommand,
)
from components.remediation.application.providers.remediation_provider import (
    build_remediation_service,
)
from components.remediation.domain.errors import EntryGateNotSatisfiedError
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


def _finding_task(workspace, owner, team, column, *, resolved: bool, draft_pr_url: str | None):
    from infrastructure.persistence.project.models import Task

    payload = {"fingerprint": "fp-abc", "triage": {"status": "triaged"}}
    if draft_pr_url:
        payload["draft_pr"] = {"url": draft_pr_url, "repo": "acme/repo", "branch": "fix/x"}
    metadata = {
        "provenance": {
            "events": [
                {"actor": "detector:logwatch", "action": "filed finding", "at": "t0"},
                {"actor": "agent:triage_agent via user:u1", "action": "opened draft PR", "at": "t1"},
            ]
        },
        "triage": {"status": "resolved" if resolved else "triaged"},
        "payload": payload,
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


def _service(*, approved: bool):
    # Real store + real board-facts adapter; sign-off faked (no ORM in the fork).
    return build_remediation_service(
        store=DjangoRemediationEntryRepository(),
        sign_off_gate=FakeSignOffGate(approved=approved),
        finding_facts=BoardFindingFactsRepository(),
    )


def _command(workspace, task, **overrides):
    base = dict(
        workspace_id=workspace.id,
        finding_task_id=str(task.id),
        sign_off_artifact_type="remediation",
        sign_off_artifact_id="signoff-1",
        pr_applied=True,
        applied_pr_url=_PR_URL,
        code="raw <fix> code",
        language="python",
        title="Fix casing import",
    )
    base.update(overrides)
    return RecordRemediationEntryCommand(**base)


class TestGateAdmitsPersisted:
    def test_all_three_met_writes_one_entry_linked_and_raw(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column, resolved=True, draft_pr_url=_PR_URL)

        entry = _service(approved=True).record(_command(ws, task, code="<b>raw</b>"))

        rows = list(Row.active.filter(workspace_id=ws.id))
        assert len(rows) == 1
        row = rows[0]
        # Provenance is LINKED (the newest board event), not duplicated.
        assert row.provenance_event_ref == "agent:triage_agent via user:u1@t1"
        assert row.finding_task_id == str(task.id)
        assert row.finding_fingerprint == "fp-abc"
        assert row.finding_kind == "log_watch"  # ai. prefix stripped
        # Code is RAW — angle brackets survive; no HTML entity encoding.
        assert row.code == "<b>raw</b>"
        assert entry.applied_pr_url == _PR_URL


class TestGateRefusesPersisted:
    def test_not_resolved_refuses_and_writes_nothing(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column, resolved=False, draft_pr_url=_PR_URL)
        with pytest.raises(EntryGateNotSatisfiedError):
            _service(approved=True).record(_command(ws, task))
        assert Row.objects.filter(workspace_id=ws.id).count() == 0

    def test_no_draft_pr_refuses_and_writes_nothing(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column, resolved=True, draft_pr_url=None)
        with pytest.raises(EntryGateNotSatisfiedError):
            _service(approved=True).record(_command(ws, task))
        assert Row.objects.filter(workspace_id=ws.id).count() == 0

    def test_not_approved_refuses_and_writes_nothing(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column, resolved=True, draft_pr_url=_PR_URL)
        with pytest.raises(EntryGateNotSatisfiedError):
            _service(approved=False).record(_command(ws, task))
        assert Row.objects.filter(workspace_id=ws.id).count() == 0


class TestTenantIsolation:
    def test_facts_never_cross_workspace(self, workspace_factory, team_factory):
        # A task lives in workspace A; asking for it under workspace B's id must
        # resolve to exists=False (so the gate refuses) — never leak A's finding.
        ws_a, owner_a, team_a, col_a = _board(workspace_factory, team_factory)
        ws_b = workspace_factory()
        task_a = _finding_task(ws_a, owner_a, team_a, col_a, resolved=True, draft_pr_url=_PR_URL)

        facts = BoardFindingFactsRepository().get_facts(workspace_id=str(ws_b.id), finding_task_id=str(task_a.id))
        assert facts.exists is False
        assert facts.draft_pr_url is None

    def test_list_for_workspace_is_scoped(self, workspace_factory, team_factory):
        ws_a, owner_a, team_a, col_a = _board(workspace_factory, team_factory)
        ws_b = workspace_factory()
        task_a = _finding_task(ws_a, owner_a, team_a, col_a, resolved=True, draft_pr_url=_PR_URL)
        _service(approved=True).record(_command(ws_a, task_a))

        store = DjangoRemediationEntryRepository()
        assert len(store.list_for_workspace(ws_a.id)) == 1
        assert store.list_for_workspace(ws_b.id) == []  # B never sees A's entry


class TestRevocation:
    def test_revoked_entry_leaves_active_corpus_but_keeps_row(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column, resolved=True, draft_pr_url=_PR_URL)
        store = DjangoRemediationEntryRepository()
        entry = _service(approved=True).record(_command(ws, task))

        store.save(entry.revoked())  # P5 revocation is a soft-delete

        assert store.list_for_workspace(ws.id) == []  # gone from retrievable corpus
        assert Row.objects.filter(id=entry.id).count() == 1  # audit row survives
