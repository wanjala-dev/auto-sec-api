"""Integration tests: the project-owned read seams consumed by later PRs.

Pins the contract of the two additive read ports (PR-0b of the app-layer ORM
burndown):

* :class:`TaskLookupPort` — the ``persist_finding_as_task`` idempotency lookup
  (hit/miss) and the ``ai_governance_service.hitl_ledger`` draft-PR scan.
* :class:`PostureFactsPort` — the ``posture_service`` finding-facts collector
  (open ∪ window-touched, deduped) and the ``forward_outlook`` creation count.

Every read is asserted workspace-scoped (no cross-workspace leak).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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


def _finding(workspace, owner, team, column, *, source_type="ai.log_watch", metadata=None):
    from infrastructure.persistence.project.models import Task

    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="[HIGH] celery_worker · ImportError",
        source_type=source_type,
        metadata=metadata or {},
    )


@pytest.mark.django_db
class TestTaskLookupIdempotency:
    def test_find_by_idempotency_hit_returns_task_id(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column, metadata={"idempotency_key": "evt-123"})

        port = ProjectProvider.build_task_lookup_port()
        found = port.find_by_idempotency(workspace_id=str(workspace.id), source_type="ai.log_watch", key="evt-123")

        assert found == task.id

    def test_find_by_idempotency_miss_returns_none(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        _finding(workspace, owner, team, column, metadata={"idempotency_key": "evt-123"})

        port = ProjectProvider.build_task_lookup_port()
        # Different key, and different source_type, both miss.
        assert (
            port.find_by_idempotency(workspace_id=str(workspace.id), source_type="ai.log_watch", key="evt-999") is None
        )
        assert port.find_by_idempotency(workspace_id=str(workspace.id), source_type="ai.other", key="evt-123") is None

    def test_empty_key_never_matches(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        # A finding with no idempotency_key stored.
        _finding(workspace, owner, team, column, metadata={})

        port = ProjectProvider.build_task_lookup_port()
        assert port.find_by_idempotency(workspace_id=str(workspace.id), source_type="ai.log_watch", key="") is None

    def test_idempotency_is_workspace_scoped(self, workspace_factory, team_factory):
        ws_a, owner_a, team_a, column_a = _board(workspace_factory, team_factory)
        ws_b, _, _, _ = _board(workspace_factory, team_factory)
        _finding(ws_a, owner_a, team_a, column_a, metadata={"idempotency_key": "evt-123"})

        port = ProjectProvider.build_task_lookup_port()
        # The same key in workspace B does not resolve workspace A's task.
        assert port.find_by_idempotency(workspace_id=str(ws_b.id), source_type="ai.log_watch", key="evt-123") is None


@pytest.mark.django_db
class TestTaskLookupDraftPrLedger:
    def test_lists_only_findings_with_a_draft_pr_url(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        with_pr = _finding(
            workspace,
            owner,
            team,
            column,
            metadata={
                "payload": {
                    "draft_pr": {
                        "url": "https://github.com/wanjala-dev/auto-sec-api/pull/7",
                        "repo": "wanjala-dev/auto-sec-api",
                        "branch": "autosec/finding-x",
                        "opened_by": str(owner.id),
                        "opened_at": "2026-07-30T00:00:00+00:00",
                    }
                }
            },
        )
        # No draft PR → excluded.
        _finding(workspace, owner, team, column, metadata={"payload": {}})
        # draft_pr with empty url → excluded.
        _finding(workspace, owner, team, column, metadata={"payload": {"draft_pr": {"url": ""}}})

        port = ProjectProvider.build_task_lookup_port()
        rows = port.list_draft_pr_findings(workspace_id=str(workspace.id))

        assert [r.task_id for r in rows] == [with_pr.id]
        row = rows[0]
        assert row.url.endswith("/pull/7")
        assert row.repo == "wanjala-dev/auto-sec-api"
        assert row.branch == "autosec/finding-x"
        assert row.opened_by == str(owner.id)
        assert row.opened_at == "2026-07-30T00:00:00+00:00"

    def test_draft_pr_ledger_is_workspace_scoped(self, workspace_factory, team_factory):
        ws_a, owner_a, team_a, column_a = _board(workspace_factory, team_factory)
        ws_b, owner_b, team_b, column_b = _board(workspace_factory, team_factory)
        _finding(
            ws_a,
            owner_a,
            team_a,
            column_a,
            metadata={"payload": {"draft_pr": {"url": "https://example/pr/1"}}},
        )

        port = ProjectProvider.build_task_lookup_port()
        assert port.list_draft_pr_findings(workspace_id=str(ws_b.id)) == []
        assert len(port.list_draft_pr_findings(workspace_id=str(ws_a.id))) == 1


@pytest.mark.django_db
class TestPostureFactsCollector:
    def test_collects_open_and_window_touched_deduped(self, workspace_factory, team_factory):
        from infrastructure.persistence.project.models import Task

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        now = datetime.now(UTC)
        window_start = now - timedelta(days=7)

        open_card = _finding(
            workspace, owner, team, column, metadata={"severity": "high", "triage": {"status": "pending"}}
        )
        # A done card that was NOT touched in the window → excluded.
        old_done = _finding(workspace, owner, team, column, metadata={"severity": "low"})
        Task.objects.filter(id=old_done.id).update(status="done", updated_at=now - timedelta(days=30))
        # The posture report's own card → always excluded.
        _finding(workspace, owner, team, column, source_type="ai.posture_report")

        port = ProjectProvider.build_posture_facts_port()
        findings = port.collect_finding_facts(workspace_id=str(workspace.id), window_start=window_start)

        ids = {f.id for f in findings}
        assert str(open_card.id) in ids
        assert str(old_done.id) not in ids
        # No dupes even though open_card matches both querysets.
        assert len(findings) == len({f.id for f in findings})
        # DTO carries the fields the posture math reads.
        row = next(f for f in findings if f.id == str(open_card.id))
        assert row.severity == "high"
        assert row.kind == "ai.log_watch"
        assert row.status == "todo"

    def test_collect_is_workspace_scoped(self, workspace_factory, team_factory):
        ws_a, owner_a, team_a, column_a = _board(workspace_factory, team_factory)
        ws_b, _, _, _ = _board(workspace_factory, team_factory)
        _finding(ws_a, owner_a, team_a, column_a, metadata={"severity": "high"})

        port = ProjectProvider.build_posture_facts_port()
        window_start = datetime.now(UTC) - timedelta(days=7)
        assert port.collect_finding_facts(workspace_id=str(ws_b.id), window_start=window_start) == []
        assert len(port.collect_finding_facts(workspace_id=str(ws_a.id), window_start=window_start)) == 1

    def test_count_findings_created_half_open_window(self, workspace_factory, team_factory):
        from infrastructure.persistence.project.models import Task

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        now = datetime.now(UTC)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        this_week = _finding(workspace, owner, team, column)
        last_week = _finding(workspace, owner, team, column)
        report_card = _finding(workspace, owner, team, column, source_type="ai.posture_report")
        Task.objects.filter(id=last_week.id).update(created_at=now - timedelta(days=10))
        Task.objects.filter(id=report_card.id).update(created_at=now - timedelta(days=1))

        port = ProjectProvider.build_posture_facts_port()

        # this-week window [week_ago, now) → only this_week; report card excluded.
        assert port.count_findings_created(workspace_id=str(workspace.id), since=week_ago) == 1
        # last-week window [two_weeks_ago, week_ago) → only last_week.
        assert port.count_findings_created(workspace_id=str(workspace.id), since=two_weeks_ago, until=week_ago) == 1
        _ = this_week

    def test_count_is_workspace_scoped(self, workspace_factory, team_factory):
        ws_a, owner_a, team_a, column_a = _board(workspace_factory, team_factory)
        ws_b, _, _, _ = _board(workspace_factory, team_factory)
        _finding(ws_a, owner_a, team_a, column_a)

        port = ProjectProvider.build_posture_facts_port()
        since = datetime.now(UTC) - timedelta(days=7)
        assert port.count_findings_created(workspace_id=str(ws_b.id), since=since) == 0
        assert port.count_findings_created(workspace_id=str(ws_a.id), since=since) == 1

    def test_count_findings_created_by_date_buckets_and_excludes(self, workspace_factory, team_factory):
        from infrastructure.persistence.project.models import Task

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        now = datetime.now(UTC)
        since = now - timedelta(days=7)

        # Two cards created on the same day, one on an earlier day, plus the
        # report card (always excluded) and one older than the window.
        today_a = _finding(workspace, owner, team, column)
        today_b = _finding(workspace, owner, team, column)
        three_days = _finding(workspace, owner, team, column)
        report_card = _finding(workspace, owner, team, column, source_type="ai.posture_report")
        too_old = _finding(workspace, owner, team, column)
        Task.objects.filter(id=three_days.id).update(created_at=now - timedelta(days=3))
        Task.objects.filter(id=report_card.id).update(created_at=now - timedelta(days=1))
        Task.objects.filter(id=too_old.id).update(created_at=now - timedelta(days=30))

        port = ProjectProvider.build_posture_facts_port()
        by_date, present = port.count_findings_created_by_date(workspace_id=str(workspace.id), since=since)

        assert present is True
        assert by_date[now.date().isoformat()] == 2  # today_a + today_b
        assert by_date[(now - timedelta(days=3)).date().isoformat()] == 1
        # report card + out-of-window card contribute nothing.
        assert sum(by_date.values()) == 3
        _ = (today_a, today_b)

    def test_count_findings_created_by_date_empty_is_absent(self, workspace_factory, team_factory):
        ws_a, owner_a, team_a, column_a = _board(workspace_factory, team_factory)
        ws_b, _, _, _ = _board(workspace_factory, team_factory)
        _finding(ws_a, owner_a, team_a, column_a)

        port = ProjectProvider.build_posture_facts_port()
        since = datetime.now(UTC) - timedelta(days=7)
        # Workspace B has no findings → empty mapping + present False.
        by_date, present = port.count_findings_created_by_date(workspace_id=str(ws_b.id), since=since)
        assert by_date == {}
        assert present is False
