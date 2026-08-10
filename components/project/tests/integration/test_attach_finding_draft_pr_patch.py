"""Integration tests: the owning-context patch-attach write (legacy record repair).

``project`` owns the board ``Task``, so it owns the write that fills a legacy
draft-PR record's missing patch — the integrations backfill asks for it through
``RecordFindingDraftPrPort`` (architecture-skill C2). These tests pin the contract
the HUD depends on:

* a patch-less record gains ``path`` / ``diff`` (+ the PR's lifecycle state) while
  every identity fact the open step wrote survives untouched;
* re-running is a no-op — a record that already carries a diff is left alone;
* an absent record / absent task / empty diff each SKIP with a named reason;
* the stored diff obeys the same bound the open step's diff obeys.
"""

from __future__ import annotations

import pytest

from components.project.application.ports.record_finding_draft_pr_port import (
    DRAFT_PR_DIFF_MAX_CHARS,
    DRAFT_PR_DIFF_TRUNCATION_MARKER,
    AttachDraftPrPatchCommand,
)
from components.project.application.providers.project_provider import ProjectProvider

_LEGACY_RECORD = {
    "url": "https://github.com/wanjala-dev/api-v0.2.0/pull/867",
    "repo": "wanjala-dev/api-v0.2.0",
    "branch": "autosec/finding-9846",
    "opened_by": "11111111-1111-1111-1111-111111111111",
    "opened_at": "2026-07-20T00:00:00+00:00",
    "verification": "unverified",
    "verification_gap": "no named anchor",
}

_DIFF = (
    "--- a/components/identity/infrastructure/adapters/apple_auth.py\n"
    "+++ b/components/identity/infrastructure/adapters/apple_auth.py\n"
    "@@ -37,7 +37,7 @@\n"
    "-    payload = jwt.decode(token, options={'verify_signature': False})\n"
    "+    payload = jwt.decode(token, key, algorithms=['RS256'])\n"
)


def _board(workspace_factory, team_factory):
    from infrastructure.persistence.project.models import Column

    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _finding(workspace, owner, team, column, *, draft_pr=None):
    from infrastructure.persistence.project.models import Task

    payload = {"service": "identity", "severity": "high"}
    if draft_pr is not None:
        payload["draft_pr"] = draft_pr
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="JWT accepted without signature verification",
        source_type="ai.code_security",
        metadata={
            "provenance": {"events": [{"actor": "detector:sast", "action": "filed", "at": "t0"}]},
            "triage": {"status": "triaged"},
            "payload": payload,
        },
    )


def _attach(workspace, task, **overrides):
    base = {
        "workspace_id": str(workspace.id),
        "task_id": str(task.id),
        "path": "components/identity/infrastructure/adapters/apple_auth.py",
        "diff": _DIFF,
        "pr_state": "open",
        "merged": False,
        "reason": "legacy_patch_backfill",
    }
    base.update(overrides)
    return ProjectProvider.build_attach_finding_draft_pr_patch_use_case().execute(
        command=AttachDraftPrPatchCommand(**base)
    )


@pytest.mark.django_db
class TestAttachFindingDraftPrPatch:
    def test_fills_missing_patch_without_disturbing_the_record(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=dict(_LEGACY_RECORD))

        result = _attach(workspace, task)

        assert result.attached is True
        task.refresh_from_db()
        draft = task.metadata["payload"]["draft_pr"]
        assert draft["diff"] == _DIFF
        assert draft["path"] == "components/identity/infrastructure/adapters/apple_auth.py"
        assert draft["change_summary"] == ""  # never invented
        assert draft["pr_state"] == "open"
        assert draft["merged"] is False
        # Every identity fact the open step wrote is preserved verbatim.
        for key, value in _LEGACY_RECORD.items():
            assert draft[key] == value, key

    def test_stamps_a_reason_bearing_provenance_event(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=dict(_LEGACY_RECORD))

        _attach(workspace, task)

        task.refresh_from_db()
        event = task.metadata["provenance"]["events"][-1]
        assert event["actor"] == "system:autosec"
        assert "legacy_patch_backfill" in event["action"]
        assert event["at"]
        # A record repair is not an AI action ON the finding — it must not claim to
        # be the last agent that handled the card.
        assert "last_handled_by" not in task.metadata["provenance"]

    def test_adds_no_card_comment(self, workspace_factory, team_factory):
        from infrastructure.persistence.project.models import TaskComment

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=dict(_LEGACY_RECORD))

        _attach(workspace, task)

        # The PR was announced when it was opened; the repair re-announces nothing.
        assert TaskComment.objects.filter(task=task).count() == 0

    def test_records_a_merged_prs_state_alongside_its_patch(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=dict(_LEGACY_RECORD))

        result = _attach(workspace, task, pr_state="closed", merged=True)

        assert result.attached is True
        task.refresh_from_db()
        draft = task.metadata["payload"]["draft_pr"]
        assert draft["diff"] == _DIFF  # a merged PR still had a patch
        assert draft["pr_state"] == "closed"
        assert draft["merged"] is True

    def test_is_idempotent_when_a_diff_is_already_stored(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        already = dict(_LEGACY_RECORD, path="old/path.py", diff="--- a/old\n+++ b/old\n@@ @@\n-x\n+y\n")
        task = _finding(workspace, owner, team, column, draft_pr=already)

        result = _attach(workspace, task)

        assert result.attached is False
        assert result.reason == "already_has_diff"
        task.refresh_from_db()
        draft = task.metadata["payload"]["draft_pr"]
        assert draft["diff"] == already["diff"]  # untouched
        assert draft["path"] == "old/path.py"
        assert len(task.metadata["provenance"]["events"]) == 1  # no repair event appended

    def test_skips_a_finding_with_no_draft_pr_record(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=None)

        result = _attach(workspace, task)

        assert result.attached is False
        assert result.reason == "no_draft_pr_record"

    def test_skips_a_task_that_no_longer_exists(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=dict(_LEGACY_RECORD))
        task_id = task.id
        task.delete()

        result = ProjectProvider.build_attach_finding_draft_pr_patch_use_case().execute(
            command=AttachDraftPrPatchCommand(
                workspace_id=str(workspace.id), task_id=str(task_id), path="a.py", diff=_DIFF
            )
        )

        assert result.attached is False
        assert result.reason == "task_not_found"

    def test_refuses_an_empty_diff(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=dict(_LEGACY_RECORD))

        result = _attach(workspace, task, diff="   \n  ")

        assert result.attached is False
        assert result.reason == "empty_diff"
        task.refresh_from_db()
        assert "diff" not in task.metadata["payload"]["draft_pr"]

    def test_bounds_an_oversized_diff(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, draft_pr=dict(_LEGACY_RECORD))

        result = _attach(workspace, task, diff="+" * (DRAFT_PR_DIFF_MAX_CHARS + 5_000))

        assert result.attached is True
        task.refresh_from_db()
        stored = task.metadata["payload"]["draft_pr"]["diff"]
        assert stored.endswith(DRAFT_PR_DIFF_TRUNCATION_MARKER)
        assert len(stored) == DRAFT_PR_DIFF_MAX_CHARS + len(DRAFT_PR_DIFF_TRUNCATION_MARKER)
