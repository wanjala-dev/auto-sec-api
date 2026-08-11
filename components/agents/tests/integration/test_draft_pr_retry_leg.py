"""A rejected draft PR must free its slot, and the queue must drain.

The bug, measured live: the throttle counts a finding's draft PR until the finding
is RESOLVED, and only a MERGED PR resolves one — so a patch the operator closed
without merging held its slot forever. After closing all three open PRs on GitHub,
`count_open_draft_prs` still returned 3/3, and Auto-Sec could never open another PR
against that repo. Rejecting bad patches is exactly what a careful operator does,
so the product punished the correct behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.infrastructure.adapters.board_finding_facts_reader import BoardFindingFactsReader
from components.project.application.ports.record_finding_draft_pr_port import MarkDraftPrRejectedCommand
from components.project.application.providers.project_provider import ProjectProvider
from infrastructure.persistence.project.models import Column, Task

_SOURCE = "ai.code_security"
_REPO = "wanjala-dev/api-v0.2.0"


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _finding(workspace, owner, team, column, *, pr_url="", severity="high", pr_state="", suggested="Parameterise it."):
    payload = {
        "repo": _REPO,
        "path": "api/scripts/migrate_schema.py",
        "severity": severity,
        "suggested_fix": suggested,
    }
    if pr_url:
        payload["draft_pr"] = {"url": pr_url, "repo": _REPO, "branch": "autosec/x", "diff": "--- a\n+++ b\n"}
        if pr_state:
            payload["draft_pr"]["pr_state"] = pr_state
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="High: sql-execute-format",
        source_type=_SOURCE,
        metadata={"agent_type": "code_security_agent", "triage": {"status": "triaged"}, "payload": payload},
    )


@pytest.mark.django_db
class TestRejectedPrFreesTheThrottle:
    def _count(self, workspace):
        return BoardFindingFactsReader().count_open_draft_prs(
            workspace_id=str(workspace.id), source_type=_SOURCE, repo=_REPO
        )

    def test_open_pr_holds_a_slot(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1")
        assert self._count(workspace) == 1

    def test_rejected_pr_releases_its_slot(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1")
        assert self._count(workspace) == 1

        result = ProjectProvider.build_mark_finding_draft_pr_rejected_use_case().execute(
            command=MarkDraftPrRejectedCommand(workspace_id=str(workspace.id), task_id=str(task.id))
        )

        assert result.marked is True
        assert self._count(workspace) == 0, "a closed-without-merge PR must not hold the repo's budget"

        task.refresh_from_db()
        record = task.metadata["payload"]["draft_pr"]
        assert record["pr_state"] == "closed"
        assert record["merged"] is False
        # The attempt is KEPT — what was tried and turned down is context for the next try.
        assert record["url"] == "https://github.com/o/r/pull/1"
        assert record["diff"]
        assert any("closed without merging" in (e.get("action") or "") for e in task.metadata["provenance"]["events"])

    def test_marking_is_idempotent(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1")
        use_case = ProjectProvider.build_mark_finding_draft_pr_rejected_use_case()
        cmd = MarkDraftPrRejectedCommand(workspace_id=str(workspace.id), task_id=str(task.id))

        assert use_case.execute(command=cmd).marked is True
        second = use_case.execute(command=cmd)

        assert second.marked is False
        assert second.reason == "already_rejected"
        task.refresh_from_db()
        closes = [
            e for e in task.metadata["provenance"]["events"] if "closed without merging" in (e.get("action") or "")
        ]
        assert len(closes) == 1, "a re-run must not spam the provenance trail"

    def test_a_merged_pr_is_never_marked_rejected(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1")
        meta = task.metadata
        meta["payload"]["draft_pr"]["merged"] = True
        task.metadata = meta
        task.save(update_fields=["metadata"])

        result = ProjectProvider.build_mark_finding_draft_pr_rejected_use_case().execute(
            command=MarkDraftPrRejectedCommand(workspace_id=str(workspace.id), task_id=str(task.id))
        )
        assert result.marked is False
        assert result.reason == "already_merged"


@pytest.mark.django_db
class TestSweepReleasesAndRetries:
    # The sweep imports lazily inside the function, so the patch target is the
    # provider itself — patching the task module would bind nothing.
    _SWEEP = "components.integrations.application.providers.vcs_provider"

    def test_closed_pr_is_released_and_the_backlog_is_retried(self, workspace_factory, team_factory):
        from components.agents.infrastructure.tasks import draft_pr_retry_tasks as sweep

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        rejected = _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1")
        waiting_low = _finding(workspace, owner, team, column, severity="low")
        waiting_critical = _finding(workspace, owner, team, column, severity="critical")

        status = SimpleNamespace(allowed=True, merged=False, state="closed")
        with (
            mock.patch(
                f"{self._SWEEP}.get_check_pr_merged_use_case",
                return_value=SimpleNamespace(execute=lambda **kw: status),
            ),
            mock.patch("components.agents.infrastructure.tasks.agent_tasks.auto_draft_pr_for_finding.delay") as delay,
        ):
            result = sweep.release_rejected_draft_prs(workspace_id=str(workspace.id))

        assert result["repos_freed"] == 1
        assert result["retried"] == 1
        rejected.refresh_from_db()
        assert rejected.metadata["payload"]["draft_pr"]["pr_state"] == "closed"
        # The scarce slot goes to the worst finding, not whichever row came back first.
        assert delay.call_args.kwargs["task_id"] == str(waiting_critical.id)
        assert delay.call_args.kwargs["task_id"] != str(waiting_low.id)

    def test_a_still_open_pr_is_left_alone(self, workspace_factory, team_factory):
        from components.agents.infrastructure.tasks import draft_pr_retry_tasks as sweep

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        live = _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1")
        _finding(workspace, owner, team, column, severity="critical")

        status = SimpleNamespace(allowed=True, merged=False, state="open")
        with (
            mock.patch(
                f"{self._SWEEP}.get_check_pr_merged_use_case",
                return_value=SimpleNamespace(execute=lambda **kw: status),
            ),
            mock.patch("components.agents.infrastructure.tasks.agent_tasks.auto_draft_pr_for_finding.delay") as delay,
        ):
            result = sweep.release_rejected_draft_prs(workspace_id=str(workspace.id))

        assert result["repos_freed"] == 0
        assert delay.call_count == 0, "an open PR still holds its slot — nothing may jump the queue"
        live.refresh_from_db()
        assert "pr_state" not in live.metadata["payload"]["draft_pr"]

    def test_a_merged_pr_is_left_to_the_reconciler(self, workspace_factory, team_factory):
        from components.agents.infrastructure.tasks import draft_pr_retry_tasks as sweep

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1")

        status = SimpleNamespace(allowed=True, merged=True, state="closed")
        with (
            mock.patch(
                f"{self._SWEEP}.get_check_pr_merged_use_case",
                return_value=SimpleNamespace(execute=lambda **kw: status),
            ),
            mock.patch("components.agents.infrastructure.tasks.agent_tasks.auto_draft_pr_for_finding.delay") as delay,
        ):
            result = sweep.release_rejected_draft_prs(workspace_id=str(workspace.id))

        assert result["repos_freed"] == 0
        assert delay.call_count == 0

    def test_already_settled_records_cost_no_host_calls(self, workspace_factory, team_factory):
        from components.agents.infrastructure.tasks import draft_pr_retry_tasks as sweep

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        _finding(workspace, owner, team, column, pr_url="https://github.com/o/r/pull/1", pr_state="closed")

        calls = []

        def _execute(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(allowed=True, merged=False, state="closed")

        with (
            mock.patch(f"{self._SWEEP}.get_check_pr_merged_use_case", return_value=SimpleNamespace(execute=_execute)),
            mock.patch("components.agents.infrastructure.tasks.agent_tasks.auto_draft_pr_for_finding.delay"),
        ):
            result = sweep.release_rejected_draft_prs(workspace_id=str(workspace.id))

        assert calls == [], "a record already settled must not be re-asked of the code host"
        assert result["checked"] == 0
