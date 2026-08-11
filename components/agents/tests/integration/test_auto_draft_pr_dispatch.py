"""A triaged repo finding ALWAYS gets its draft PR — the hand-off, locked down.

The bug this pins: triage stamped "suggested a code fix" and stopped. Opening the
PR was a separate, operator-triggered task, so a finding in a connected repository
sat on the board reading FIX READY with no artifact behind it — 13 of 15 repo
findings in the live demo workspace, while the 2 that HAD PRs were the 2 where a
human had pressed the button. "Detected, then nothing" is the exact gap the
product exists to close.

These tests assert the trigger, not the engine: the PR engine's guardrails (patch
scope, validate_patch, throttle, allowlist, capability) have their own coverage and
are deliberately untouched here. What is pinned is WHEN the engine is asked, and —
just as important — when it is NOT (a finding with no repo to PR against must stay
a clean no-op, never a misleading "PR blocked" stamp).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    code_security_agent as code_security_tools,
)
from components.code_security.application.sast_fix_advisor_service import SastFixSuggestion
from infrastructure.persistence.project.models import Column, Task

_SOURCE = "ai.code_security"
_DISPATCH_PATH = "components.agents.infrastructure.tasks.agent_tasks.auto_draft_pr_for_finding.delay"
_SUGGEST_PATH = "components.code_security.application.sast_fix_advisor_service.SastFixAdvisor.suggest"

_GROUNDED = SastFixSuggestion(
    likely_cause="cursor.execute interpolates the table name into raw SQL (sql-injection rule).",
    suggested_fix="Use psycopg's sql.Identifier for the table name in migrate_schema.py instead of %-formatting.",
    confidence="high",
    fix_before='cursor.execute("DROP TABLE %s" % table)',
    fix_after='cursor.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table)))',
)


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    intake = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, team, intake


def _agent(workspace, owner):
    return SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id))


def _sast_task(workspace, owner, team, column, *, payload_extra=None):
    payload = {
        "lookup_key": "owner/repo|autosec.python.django.sql-execute-format|api/scripts/migrate_schema.py|s1",
        "signal": "Raw SQL built with %-formatting",
        "message": "Raw SQL built with %-formatting",
        "confidence": "high",
        "severity": "high",
        "rule_id": "autosec.python.django.sql-execute-format",
        "repo": "wanjala-dev/api-v0.2.0",
        "commit_sha": "abc123def456",
        "path": "api/scripts/migrate_schema.py",
        "start_line": 42,
        "end_line": 42,
        "snippet": 'cursor.execute("DROP TABLE %s" % table)',
        "language": "python",
        "triage": {"status": "pending"},
    }
    payload.update(payload_extra or {})
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="High: sql-execute-format — api/scripts/migrate_schema.py:42",
        source_type=_SOURCE,
        metadata={"agent_type": "code_security_agent", "payload": payload},
    )


@pytest.mark.django_db
class TestAutoDraftPrDispatch:
    def test_triaged_repo_finding_dispatches_its_draft_pr(
        self, workspace_factory, team_factory, django_capture_on_commit_callbacks
    ):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _sast_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        with mock.patch(_SUGGEST_PATH, return_value=_GROUNDED), mock.patch(_DISPATCH_PATH) as delay:
            with django_capture_on_commit_callbacks(execute=True):
                code_security_tools.triage_code_finding(agent, str(task.id))

        assert delay.call_count == 1, "a triaged repo finding must hand off to the draft-PR engine"
        kwargs = delay.call_args.kwargs
        assert kwargs["task_id"] == str(task.id)
        assert kwargs["workspace_id"] == str(workspace.id)
        # IDs only across the queue boundary, and an acting identity so the commit
        # and the audit trail can name who the agent acted as.
        assert kwargs["performed_by"] == str(owner.id)
        assert kwargs["acting_agent"] == "code_security_agent"

    def test_dispatch_waits_for_commit(self, workspace_factory, team_factory, django_capture_on_commit_callbacks):
        """The worker re-reads the card — enqueuing before commit races the write."""
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _sast_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        with mock.patch(_SUGGEST_PATH, return_value=_GROUNDED), mock.patch(_DISPATCH_PATH) as delay:
            with django_capture_on_commit_callbacks(execute=False) as callbacks:
                code_security_tools.triage_code_finding(agent, str(task.id))
                assert delay.call_count == 0, "must not enqueue inside the transaction"
            assert callbacks, "the dispatch must be registered as an on_commit callback"

    def test_finding_that_already_has_a_pr_is_not_dispatched_again(
        self, workspace_factory, team_factory, django_capture_on_commit_callbacks
    ):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _sast_task(
            workspace, owner, team, intake, payload_extra={"draft_pr": {"url": "https://github.com/o/r/pull/1"}}
        )
        agent = _agent(workspace, owner)

        with mock.patch(_SUGGEST_PATH, return_value=_GROUNDED), mock.patch(_DISPATCH_PATH) as delay:
            with django_capture_on_commit_callbacks(execute=True):
                code_security_tools.triage_code_finding(agent, str(task.id))

        assert delay.call_count == 0, "a second PR must never be opened for the same finding"


@pytest.mark.django_db
class TestAutoDraftPrTask:
    """The task itself: idempotent, thin, and attributed to the AGENT."""

    def _run(self, task):
        from components.agents.infrastructure.tasks import agent_tasks

        return agent_tasks.auto_draft_pr_for_finding(
            workspace_id=str(task.workspace_id),
            task_id=str(task.id),
            performed_by=str(task.created_by_id),
            acting_agent="code_security_agent",
        )

    def test_no_op_when_a_pr_already_exists(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _sast_task(
            workspace, owner, team, intake, payload_extra={"draft_pr": {"url": "https://github.com/o/r/pull/1"}}
        )

        with mock.patch("components.agents.infrastructure.tasks.agent_tasks._open_draft_pr_for_finding") as engine:
            result = self._run(task)

        assert result == {"success": True, "reason": "already_open"}
        assert engine.call_count == 0

    def test_missing_card_is_reported_not_raised(self, workspace_factory, team_factory):
        from components.agents.infrastructure.tasks import agent_tasks

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        result = agent_tasks.auto_draft_pr_for_finding(
            workspace_id=str(workspace.id),
            task_id="999999999",  # board cards are integer-keyed
            performed_by=str(owner.id),
        )
        assert result == {"success": False, "error": "finding_not_found"}

    def test_delegates_to_the_one_pr_engine_and_records_agent_attribution(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _sast_task(workspace, owner, team, intake)

        with mock.patch(
            "components.agents.infrastructure.tasks.agent_tasks._open_draft_pr_for_finding",
            return_value={"pr_url": "https://github.com/o/r/pull/9"},
        ) as engine:
            result = self._run(task)

        assert engine.call_count == 1
        assert result["pr_url"] == "https://github.com/o/r/pull/9"
        task.refresh_from_db()
        events = (task.metadata.get("provenance") or {}).get("events") or []
        actors = [e.get("actor") for e in events]
        assert any(a == "agent:code_security_agent" for a in actors), (
            "the board must show the AGENT opened this off its own triage — not that a human asked"
        )
