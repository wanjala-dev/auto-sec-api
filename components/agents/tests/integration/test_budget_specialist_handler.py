"""Integration test: BookBalanceFindingsDetected → Task.

Phase 3 of the Agents-as-Teammates migration
(``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md``). Post-Phase-5
(``AIAction`` retired), the budget specialist handler subscribes to
``BookBalanceFindingsDetected`` and:

1. Calls ``ensure_agents_board`` to guarantee the team / project /
   columns exist.
2. Creates a Kanban Task in "Suggested" per finding group, carrying
   narrative on ``Task.description`` and detector context on
   ``Task.metadata``.

Idempotency: re-firing the same event is a no-op because the helper
checks ``(workspace, source_type, metadata.idempotency_key)`` before
writing, where the key is ``period:<period>:kind:<kind>``.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from components.agents.application.handlers.budget_specialist_handler import (
    handle_book_balance_findings_detected,
)
from components.budgeting.domain.events.book_balance_findings_detected_event import (
    BookBalanceFindingsDetected,
)


def _build_event(
    *,
    workspace_id: UUID,
    period: str = "2026-06-05",
    headline: str | None = "Two budget areas need attention",
    narrative: str | None = (
        "Education category is 23% over plan and donations are short "
        "this month."
    ),
    grouped_findings: tuple[dict, ...] | None = None,
) -> BookBalanceFindingsDetected:
    if grouped_findings is None:
        grouped_findings = (
            {
                "kind": "budget_overrun",
                "severity": "high",
                "title": "Education category 23% over plan",
                "summary": "Spend is $230 above the planned envelope.",
                "item_count": 1,
                "impact_score": 80,
                "items": [
                    {"category": "Education", "variance_pct": 23, "amount": 230},
                ],
            },
            {
                "kind": "cash_flow_negative",
                "severity": "medium",
                "title": "Cash flow negative for the window",
                "summary": "Expenses exceeded income by $150 over the last 30 days.",
                "item_count": 1,
                "impact_score": 50,
                "items": [{"net_flow": -150}],
            },
        )
    return BookBalanceFindingsDetected(
        workspace_id=workspace_id,
        detector_key="book_balance_daily",
        window_start=date(2026, 5, 6),
        window_end=date(2026, 6, 5),
        period=period,
        ai_headline=headline,
        ai_narrative=narrative,
        grouped_findings=grouped_findings,
    )


@pytest.mark.django_db
class TestBudgetSpecialistHandler:
    def test_creates_task_per_group(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_book_balance_findings_detected(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace,
                source_type__startswith="ai.book_balance.",
            ).order_by("source_type")
        )
        assert len(tasks) == 2

        source_types = {t.source_type for t in tasks}
        assert source_types == {
            "ai.book_balance.budget_overrun",
            "ai.book_balance.cash_flow_negative",
        }

        for task in tasks:
            assert task.metadata["agent_type"] == "budget_specialist"
            assert task.metadata["detector"] == "book_balance_daily"
            assert task.workspace_id == workspace.id
            # Eyeball check that context carries the narrative for the
            # frontend widgets that read it.
            assert task.metadata["context"]["period"] == "2026-06-05"
            assert task.metadata["context"].get("ai_headline")

    def test_one_task_per_group_no_doubles(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_book_balance_findings_detected(event)

        task_count = Task.objects.filter(
            workspace=workspace,
            source_type__startswith="ai.book_balance.",
        ).count()
        # Two findings, two Tasks — never four.
        assert task_count == 2

    def test_idempotent_on_period_kind_dedup(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_book_balance_findings_detected(event)
        handle_book_balance_findings_detected(event)  # second pass — no-op

        assert (
            Task.objects.filter(
                workspace=workspace,
                source_type__startswith="ai.book_balance.",
            ).count()
            == 2
        )

    def test_handles_workspace_missing_gracefully(self):
        from uuid import uuid4

        # A workspace_id pointing nowhere must NOT raise — the
        # detector run may have raced a workspace deletion.
        event = _build_event(workspace_id=uuid4())
        handle_book_balance_findings_detected(event)
        # No assertion — just don't blow up.

    def test_per_group_failure_does_not_void_other_groups(
        self, workspace_factory, monkeypatch
    ):
        """If one group's writes raise (e.g. a transient DB error), the
        other groups in the same event still get persisted. Each group
        is wrapped in its own try / transaction.atomic, so failures are
        contained."""
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        from components.project.application.providers.project_provider import (
            ProjectProvider,
        )

        original_build = ProjectProvider.build_create_task_use_case
        call_count = {"n": 0}

        def flaky_build():
            use_case = original_build()
            original_execute_fn = use_case.execute

            def execute(*, command):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("transient DB blip")
                return original_execute_fn(command=command)

            use_case.execute = execute
            return use_case

        monkeypatch.setattr(
            ProjectProvider, "build_create_task_use_case", flaky_build
        )

        handle_book_balance_findings_detected(event)

        # Only the second group survives — the first raised inside its
        # atomic block, leaving no Task for it.
        assert (
            Task.objects.filter(
                workspace=workspace,
                source_type__startswith="ai.book_balance.",
            ).count()
            == 1
        )
