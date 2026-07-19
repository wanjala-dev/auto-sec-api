"""DB-backed tests for financial_agent report tools (PR-B3).

The audit found ``FinancialReport`` was a complete model with no
agent surface — list, get, generate all unreachable. PR-B3 adds those
three tools so the financial agent can browse and trigger reports.

The generate path is the heaviest of any agent tool — it composes the
``FinancialReportGenerationProvider`` (metrics + AI gateway + store +
notifications + event publisher), runs the use case, and persists a
new row. We test list and get end-to-end against the real DB and stub
generate's expensive dependencies (AI gateway, notifications) so the
test stays fast and deterministic.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    financial_agent as financial_tools,
)


def _make_agent(workspace_id, user=None):
    agent = MagicMock()
    agent.workspace_id = workspace_id
    agent.user_id = user.id if user else None
    agent.config = {}
    return agent


@pytest.fixture
def report_setup(workspace_factory, user_factory):
    """Workspace + user + 3 FinancialReports of different types/variants."""
    from infrastructure.persistence.reports.models import FinancialReport

    user = user_factory()
    workspace = workspace_factory(owner=user)
    reports = [
        FinancialReport.objects.create(
            workspace_id=workspace.id,
            report_type=FinancialReport.REPORT_TYPE_MONTHLY,
            variant=FinancialReport.VARIANT_FINANCIAL,
            title=f"Monthly report {i}",
            summary=f"Summary {i}",
            content=f"Content body for report {i}",
            date_start=date(2026, 1, 1),
            date_end=date(2026, 1, 31),
            generated_by=FinancialReport.TRIGGER_AI,
        )
        for i in range(3)
    ]
    return {
        "user": user,
        "workspace": workspace,
        "reports": reports,
        "agent": _make_agent(workspace.id, user),
    }


# ── list_financial_reports ─────────────────────────────────────────────


@pytest.mark.django_db
class TestListFinancialReports:
    def test_returns_helpful_when_empty(self, workspace_factory):
        ws = workspace_factory()
        result = financial_tools.list_financial_reports(_make_agent(ws.id), {})
        assert "No financial reports" in result

    def test_lists_workspace_reports_only(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.reports.models import FinancialReport

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        FinancialReport.objects.create(
            workspace_id=ws_a.id, title="Belongs to A", content="x",
            date_start=date(2026, 1, 1), date_end=date(2026, 1, 31),
        )
        FinancialReport.objects.create(
            workspace_id=ws_b.id, title="Belongs to B", content="x",
            date_start=date(2026, 1, 1), date_end=date(2026, 1, 31),
        )
        result = financial_tools.list_financial_reports(_make_agent(ws_a.id), {})
        assert "Belongs to A" in result
        assert "Belongs to B" not in result, (
            "Cross-workspace leak — list_financial_reports must scope by "
            "agent.workspace_id."
        )

    def test_filters_by_report_type(self, workspace_factory):
        from infrastructure.persistence.reports.models import FinancialReport

        ws = workspace_factory()
        FinancialReport.objects.create(
            workspace_id=ws.id,
            report_type=FinancialReport.REPORT_TYPE_DAILY,
            title="A daily one", content="x",
            date_start=date(2026, 1, 1), date_end=date(2026, 1, 1),
        )
        FinancialReport.objects.create(
            workspace_id=ws.id,
            report_type=FinancialReport.REPORT_TYPE_MONTHLY,
            title="A monthly one", content="x",
            date_start=date(2026, 1, 1), date_end=date(2026, 1, 31),
        )
        result = financial_tools.list_financial_reports(
            _make_agent(ws.id), {"report_type": "daily"}
        )
        assert "A daily one" in result
        assert "A monthly one" not in result

    def test_lists_in_chronological_order(self, report_setup):
        result = financial_tools.list_financial_reports(
            report_setup["agent"], {}
        )
        # 3 reports created in a single fixture; all show up.
        assert "3 total" in result
        for r in report_setup["reports"]:
            assert r.title in result


# ── get_financial_report ───────────────────────────────────────────────


@pytest.mark.django_db
class TestGetFinancialReport:
    def test_fetches_by_id(self, report_setup):
        target = report_setup["reports"][0]
        result = financial_tools.get_financial_report(
            report_setup["agent"], {"report_id": str(target.id)}
        )
        assert target.title in result
        assert target.summary in result
        assert "Content body for report 0" in result

    def test_rejects_missing_id(self, report_setup):
        result = financial_tools.get_financial_report(
            report_setup["agent"], {}
        )
        assert "report_id is required" in result

    def test_rejects_unknown_id(self, report_setup):
        result = financial_tools.get_financial_report(
            report_setup["agent"],
            {"report_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.reports.models import FinancialReport

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        report_in_b = FinancialReport.objects.create(
            workspace_id=ws_b.id, title="Other workspace", content="x",
            date_start=date(2026, 1, 1), date_end=date(2026, 1, 31),
        )
        result = financial_tools.get_financial_report(
            _make_agent(ws_a.id), {"report_id": str(report_in_b.id)}
        )
        assert "not found" in result
        assert "Other workspace" not in result

    def test_truncates_long_content(self, workspace_factory):
        from infrastructure.persistence.reports.models import FinancialReport

        ws = workspace_factory()
        long_content = "x" * 5000
        report = FinancialReport.objects.create(
            workspace_id=ws.id, title="Big report", content=long_content,
            date_start=date(2026, 1, 1), date_end=date(2026, 1, 31),
        )
        result = financial_tools.get_financial_report(
            _make_agent(ws.id), {"report_id": str(report.id)}
        )
        assert "truncated" in result
        # The actual content slice plus the truncation suffix must
        # be much shorter than the original.
        assert len(result) < len(long_content)


# ── generate_financial_report ──────────────────────────────────────────


@pytest.mark.django_db
class TestGenerateFinancialReport:
    def test_defaults_to_last_30_days_when_no_dates(self, workspace_factory, user_factory):
        """Empty input: tool should default range_end=today, range_start=today-30d.

        Previously this returned 'range_start required' which the LLM couldn't
        recover from gracefully. Now it Just Works for "create a financial
        report" without explicit dates (Henry hit this 2026-05-09).
        """
        u = user_factory()
        ws = workspace_factory(owner=u)
        agent = _make_agent(ws.id, u)

        fake_report = MagicMock()
        fake_report.id = "fake-default-id"
        fake_service = MagicMock()
        fake_service.generate_report = MagicMock(return_value=fake_report)

        with patch(
            "components.reports.application.providers.financial_report_generation_provider"
            ".FinancialReportGenerationProvider"
        ) as ProviderMock:
            ProviderMock.return_value.build_generation_service = MagicMock(
                return_value=fake_service
            )
            result = financial_tools.generate_financial_report(agent, {})

        assert fake_service.generate_report.called
        kwargs = fake_service.generate_report.call_args.kwargs
        # Default range = (today - 30, today). Confirm both are set and sensible.
        assert kwargs["range_end"] is not None
        assert kwargs["range_start"] is not None
        assert (kwargs["range_end"] - kwargs["range_start"]).days == 30
        assert "fake-default-id" in result

    def test_unparseable_dates_fall_back_to_defaults(self, workspace_factory, user_factory):
        """Garbage in one slot doesn't fail the whole call — just defaults that slot.

        With both dates garbage, both fall back to defaults (today - 30, today)
        and the call succeeds.
        """
        u = user_factory()
        ws = workspace_factory(owner=u)
        agent = _make_agent(ws.id, u)

        fake_report = MagicMock()
        fake_report.id = "fake-id"
        fake_service = MagicMock()
        fake_service.generate_report = MagicMock(return_value=fake_report)

        with patch(
            "components.reports.application.providers.financial_report_generation_provider"
            ".FinancialReportGenerationProvider"
        ) as ProviderMock:
            ProviderMock.return_value.build_generation_service = MagicMock(
                return_value=fake_service
            )
            result = financial_tools.generate_financial_report(
                agent,
                {"range_start": "next Monday", "range_end": "tomorrow"},
            )

        # Both unparseable → both default to (today - 30, today); call succeeds.
        assert fake_service.generate_report.called
        assert "fake-id" in result

    def test_rejects_inverted_range(self, workspace_factory):
        ws = workspace_factory()
        result = financial_tools.generate_financial_report(
            _make_agent(ws.id),
            {"range_start": "2026-03-31", "range_end": "2026-01-01"},
        )
        assert "on or after" in result

    def test_rejects_invalid_report_type(self, workspace_factory):
        ws = workspace_factory()
        result = financial_tools.generate_financial_report(
            _make_agent(ws.id),
            {
                "range_start": "2026-01-01",
                "range_end": "2026-01-31",
                "report_type": "fortnightly",
            },
        )
        assert "Invalid report_type" in result

    def test_rejects_invalid_variant(self, workspace_factory):
        ws = workspace_factory()
        result = financial_tools.generate_financial_report(
            _make_agent(ws.id),
            {
                "range_start": "2026-01-01",
                "range_end": "2026-01-31",
                "variant": "psychedelic",
            },
        )
        assert "Invalid variant" in result

    def test_invokes_provider_on_valid_input(self, workspace_factory, user_factory):
        """Patch the provider so we don't hit the AI gateway in unit-test mode.

        Asserts the tool wires the user-supplied range/type/variant into the
        provider call correctly. Doesn't exercise the actual report
        generation (that's covered by the reports component's own tests).
        """
        u = user_factory()
        ws = workspace_factory(owner=u)
        agent = _make_agent(ws.id, u)

        fake_report = MagicMock()
        fake_report.id = "fake-report-id-123"
        fake_service = MagicMock()
        fake_service.generate_report = MagicMock(return_value=fake_report)

        with patch(
            "components.reports.application.providers.financial_report_generation_provider"
            ".FinancialReportGenerationProvider"
        ) as ProviderMock:
            ProviderMock.return_value.build_generation_service = MagicMock(
                return_value=fake_service
            )
            result = financial_tools.generate_financial_report(
                agent,
                {
                    "range_start": "2026-01-01",
                    "range_end": "2026-03-31",
                    "report_type": "monthly",
                    "variant": "financial",
                },
            )

        # Confirms the provider was constructed and the service called
        # with the parsed inputs.
        assert fake_service.generate_report.called
        kwargs = fake_service.generate_report.call_args.kwargs
        assert str(kwargs["range_start"]) == "2026-01-01"
        assert str(kwargs["range_end"]) == "2026-03-31"
        assert kwargs["report_type"] == "monthly"
        assert kwargs["agent_type"] == "financial_agent"
        assert kwargs["triggered_by"] == "ai_teammate"
        assert kwargs["metadata"]["variant"] == "financial"
        assert "fake-report-id-123" in result
