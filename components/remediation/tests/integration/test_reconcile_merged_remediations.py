"""End-to-end reconciler over the real board + real gate (ADR 0012 P4a).

Proves the P4a loop against the persistence layer: a finding with an open draft PR
whose PR is verified merged gets transitioned to ``resolved`` on the board AND —
when sign-off is approved — captured into the corpus via the D1 gate. When
sign-off is NOT approved the finding still resolves but the gate refuses the entry
(no corpus write). Unmerged findings are untouched. The whole run is idempotent and
tenant-scoped.

The merge-check port is faked (no live GitHub); everything else is real — the
board-facts + resolution + open-draft-pr adapters, the gated capture facade, and
the RemediationEntry store. Sign-off is faked (the fork registers no adapter).
"""

from __future__ import annotations

import pytest

from components.remediation.application.ports.pull_request_merge_check_port import (
    MergeStatus,
    PullRequestMergeCheckPort,
)
from components.remediation.application.providers.remediation_provider import (
    build_finding_facts,
    build_finding_resolution,
    build_open_draft_pr_findings,
    build_remediation_service,
)
from components.remediation.application.use_cases.reconcile_merged_remediations_use_case import (
    ReconcileMergedRemediationsUseCase,
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


def _finding_task(workspace, owner, team, column, *, draft_pr_url=_PR_URL, suggested_fix="alias AiEmbeddingsProvider"):
    from infrastructure.persistence.project.models import Task

    payload = {"fingerprint": "fp-abc", "suggested_fix": suggested_fix, "probable_cause": "casing import"}
    if draft_pr_url:
        payload["draft_pr"] = {"url": draft_pr_url, "repo": "acme/repo", "branch": "fix/x"}
    metadata = {
        "provenance": {"events": [{"actor": "agent:triage_agent", "action": "opened draft PR", "at": "t1"}]},
        "triage": {"status": "triaged"},
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


class _FakeMergeCheck(PullRequestMergeCheckPort):
    def __init__(self, *, merged: bool, checked: bool = True):
        self._status = MergeStatus(checked=checked, merged=merged, pr_url=_PR_URL)

    def check_merged(self, *, workspace_id: str, repo: str, pr_ref: str) -> MergeStatus:
        return self._status


def _reconciler(*, merged: bool, approved: bool, checked: bool = True):
    # Real board adapters + real gate; only merge-check + sign-off are faked.
    store = DjangoRemediationEntryRepository()
    service = build_remediation_service(
        store=store,
        sign_off_gate=FakeSignOffGate(approved=approved),
        finding_facts=BoardFindingFactsRepository(),
    )

    def _capture(**kwargs):
        from components.remediation.application.handlers.remediation_capture_handler import (
            capture_remediation_if_gated,
        )

        return capture_remediation_if_gated(service=service, **kwargs)

    return ReconcileMergedRemediationsUseCase(
        candidates=build_open_draft_pr_findings(),
        merge_check=_FakeMergeCheck(merged=merged, checked=checked),
        finding_facts=build_finding_facts(),
        resolution=build_finding_resolution(),
        capture=_capture,
    )


def _reload(task):
    from infrastructure.persistence.project.models import Task

    return Task.objects.get(id=task.id)


class TestMergedApprovedCaptures:
    def test_finding_resolved_and_entry_captured(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        result = _reconciler(merged=True, approved=True).execute()

        assert result.merged == 1
        assert result.resolved == 1
        assert result.captured == 1
        # Finding transitioned to resolved on the board, with a provenance event.
        meta = _reload(task).metadata
        assert meta["triage"]["status"] == "resolved"
        assert any("finding resolved" in e["action"] for e in meta["provenance"]["events"])
        # Exactly one corpus entry, linked + raw.
        rows = list(Row.active.filter(workspace_id=ws.id))
        assert len(rows) == 1
        assert rows[0].finding_task_id == str(task.id)
        assert rows[0].applied_pr_url == _PR_URL
        assert rows[0].code == "alias AiEmbeddingsProvider"


class TestMergedNotApprovedResolvesButRefuses:
    def test_finding_resolved_but_no_entry(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        result = _reconciler(merged=True, approved=False).execute()

        assert result.resolved == 1
        assert result.captured == 0
        assert _reload(task).metadata["triage"]["status"] == "resolved"
        assert Row.objects.filter(workspace_id=ws.id).count() == 0  # gate refused


class TestUnmergedUntouched:
    def test_unmerged_leaves_finding_and_corpus_alone(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        result = _reconciler(merged=False, approved=True).execute()

        assert result.merged == 0
        assert result.resolved == 0
        assert _reload(task).metadata["triage"]["status"] == "triaged"  # unchanged
        assert Row.objects.filter(workspace_id=ws.id).count() == 0

    def test_unverifiable_merge_leaves_finding_alone(self, workspace_factory, team_factory):
        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        result = _reconciler(merged=False, approved=True, checked=False).execute()

        assert result.resolved == 0
        assert _reload(task).metadata["triage"]["status"] == "triaged"


class TestIdempotency:
    def test_second_run_no_dup_entry_no_reresolve(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding_task(ws, owner, team, column)

        first = _reconciler(merged=True, approved=True).execute()
        assert first.captured == 1

        # A resolved finding is no longer a candidate (the open-draft-pr scan skips
        # resolved). Second run touches nothing new.
        second = _reconciler(merged=True, approved=True).execute()
        assert second.scanned == 0
        assert second.captured == 0
        assert Row.active.filter(workspace_id=ws.id).count() == 1

        # Provenance did not gain a duplicate "finding resolved" event.
        events = _reload(task).metadata["provenance"]["events"]
        resolved_events = [e for e in events if "finding resolved" in e["action"]]
        assert len(resolved_events) == 1


class TestTenantScoped:
    def test_reconciler_is_workspace_scoped(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws_a, owner_a, team_a, col_a = _board(workspace_factory, team_factory)
        ws_b, owner_b, team_b, col_b = _board(workspace_factory, team_factory)
        task_a = _finding_task(ws_a, owner_a, team_a, col_a)
        _finding_task(ws_b, owner_b, team_b, col_b)

        _reconciler(merged=True, approved=True).execute()

        # Each finding's entry is filed under its OWN workspace — never crossed.
        assert Row.active.filter(workspace_id=ws_a.id).count() == 1
        assert Row.active.filter(workspace_id=ws_b.id).count() == 1
        assert Row.active.filter(workspace_id=ws_a.id).first().finding_task_id == str(task_a.id)
