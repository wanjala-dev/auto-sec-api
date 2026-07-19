"""Integration tests for the chat-bubble artifact pattern (PR-H1).

When a tool produces a downloadable result (e.g. a PDF financial
report), it calls ``agent.collect_artifact({...})``. ``BaseAgent.execute``
harvests the collector at end-of-turn and forwards the artifacts into
``record_execution(..., artifacts=...)``, which lands them on the
assistant ``ConversationMessage``'s ``metadata['artifacts']``. The chat
serializer exposes ``metadata`` directly, so the frontend bubble can
render a paperclip download icon without any extra wiring.

These tests exercise the contract end-to-end without spinning up the
full LangChain executor — the executor pieces are mocked in
``AgentTestCase.make_agent`` already, but here we go even simpler and
test the collector + memory_service path directly.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from components.agents.infrastructure.adapters.langchain.agents.donation_agent import (
    DonationAgent,
)
from components.agents.infrastructure.adapters.langchain.agents.financial_agent import (
    FinancialAgent,
)
from components.agents.infrastructure.adapters.langchain.agents.sponsorship_agent import (
    SponsorshipAgent,
)
from components.agents.infrastructure.adapters.langchain.agents.workspace_agent import (
    WorkspaceAgent,
)
from components.agents.infrastructure.adapters.langchain.tools.donation_agent import (
    generate_donation_report,
)
from components.agents.infrastructure.adapters.langchain.tools.workspace_agent import (
    generate_organization_report,
)
from components.agents.infrastructure.adapters.langchain.tools.financial_agent import (
    generate_financial_report,
)
from components.agents.infrastructure.adapters.langchain.tools.sponsorship_agent import (
    generate_sponsorship_report,
)
from infrastructure.persistence.ai.conversations.models import (
    Conversation,
    ConversationMessage,
)


def _build_smoke_agent(agent_cls, user, workspace):
    """Stub LLM + memory and skip executor build — same shortcut
    Pattern E uses, so artifact-collection tests don't need a real
    LangChain runtime."""
    fake_llm = MagicMock(name="fake_llm")
    fake_provider = MagicMock(name="fake_llm_provider")
    fake_provider.get_llm = MagicMock(return_value=fake_llm)

    fake_memory_service = MagicMock(name="fake_memory_service")
    fake_memory_service.get_memory = MagicMock(return_value=MagicMock())
    fake_memory_service.get_conversation_id = MagicMock(return_value=str(uuid.uuid4()))

    from components.agents.infrastructure.adapters.langchain import base as base_module

    with patch.object(
        base_module, "get_agent_memory_service", return_value=fake_memory_service
    ), patch.object(
        agent_cls, "_create_agent_executor", lambda self_inner: None, create=False
    ):
        return agent_cls(
            agent_id=str(uuid.uuid4()),
            user_id=str(user.id),
            workspace_id=str(workspace.id),
            llm_provider=fake_provider,
            default_user_id=str(user.id),
            default_user_email=user.email,
        )


@pytest.fixture
def chat_agent(workspace_factory, user_factory):
    """Build a real FinancialAgent against a real workspace + user."""
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = _build_smoke_agent(FinancialAgent, user, workspace)
    return {"agent": agent, "user": user, "workspace": workspace}


@pytest.fixture
def sponsorship_chat_agent(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = _build_smoke_agent(SponsorshipAgent, user, workspace)
    return {"agent": agent, "user": user, "workspace": workspace}


@pytest.fixture
def donation_chat_agent(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = _build_smoke_agent(DonationAgent, user, workspace)
    return {"agent": agent, "user": user, "workspace": workspace}


@pytest.fixture
def workspace_chat_agent(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = _build_smoke_agent(WorkspaceAgent, user, workspace)
    return {"agent": agent, "user": user, "workspace": workspace}


@pytest.mark.django_db
class TestAgentArtifactCollector:
    """``BaseAgent.collect_artifact`` accumulates per-turn artifacts."""

    def test_collect_artifact_appends_to_pending(self, chat_agent):
        agent = chat_agent["agent"]
        assert agent._pending_artifacts == []

        agent.collect_artifact({
            "kind": "financial_report",
            "id": "abc-123",
            "title": "Q1 Financials",
            "download_url": "/api/reports/financial-reports/abc-123/download/",
            "mime_type": "application/pdf",
            "status": "rendering",
        })

        assert len(agent._pending_artifacts) == 1
        artifact = agent._pending_artifacts[0]
        assert artifact["kind"] == "financial_report"
        assert artifact["id"] == "abc-123"
        assert artifact["download_url"].endswith("/download/")

    def test_collect_artifact_silently_ignores_non_dict(self, chat_agent):
        """Tools should never crash the response just because they
        passed bad input to the collector."""
        agent = chat_agent["agent"]
        agent.collect_artifact("not a dict")
        agent.collect_artifact(None)
        agent.collect_artifact(42)
        assert agent._pending_artifacts == []

    def test_collect_artifact_copies_to_decouple_caller(self, chat_agent):
        """Mutating the dict the caller passed shouldn't change the
        stored artifact — otherwise tools holding references can
        accidentally leak follow-up edits."""
        agent = chat_agent["agent"]
        payload = {"kind": "x", "id": "1"}
        agent.collect_artifact(payload)
        payload["kind"] = "MUTATED"
        assert agent._pending_artifacts[0]["kind"] == "x"


@pytest.mark.django_db
class TestGenerateFinancialReportArtifactWiring:
    """``generate_financial_report`` calls ``collect_artifact`` after
    the report row is created. The exact shape lands on the agent's
    pending list so end-of-turn harvest writes it to the chat bubble.
    """

    def _stub_report(self, report_id="report-uuid-1", title="Q1 Financials"):
        report = MagicMock()
        report.id = report_id
        report.title = title
        return report

    def test_collects_artifact_with_download_url(self, chat_agent):
        agent = chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            response = generate_financial_report(
                agent,
                {
                    "range_start": "2026-01-01",
                    "range_end": "2026-03-31",
                    "report_type": "custom",
                    "variant": "financial",
                    "use_ai": False,
                },
            )

        assert "PDF financial report" in response
        assert "paperclip" in response
        assert len(agent._pending_artifacts) == 1
        artifact = agent._pending_artifacts[0]
        assert artifact["kind"] == "financial_report"
        assert artifact["id"] == "report-uuid-1"
        assert artifact["title"] == "Q1 Financials"
        assert (
            artifact["download_url"]
            == "/api/reports/financial-reports/report-uuid-1/download/"
        )
        assert artifact["mime_type"] == "application/pdf"
        assert artifact["status"] == "rendering"

    def test_no_artifact_collected_on_error_path(self, chat_agent):
        """If the service raises, the response is an error string and
        no artifact gets attached — we don't want a paperclip pointing
        at a report that never persisted."""
        agent = chat_agent["agent"]

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            ProviderCls.return_value.build_generation_service.side_effect = (
                RuntimeError("boom")
            )

            response = generate_financial_report(
                agent,
                {"range_start": "2026-01-01", "range_end": "2026-03-31"},
            )

        assert "Error generating financial report" in response
        assert agent._pending_artifacts == []


@pytest.mark.django_db
class TestRecordExecutionWritesArtifactsToMessage:
    """The ``record_execution`` → ``add_agent_message`` →
    ``_add_message`` path stores artifacts under
    ``ConversationMessage.metadata['artifacts']``. The chat history
    serializer exposes ``metadata`` directly, so frontend reads it
    untransformed.
    """

    def test_artifacts_land_on_assistant_message_metadata(
        self, workspace_factory, user_factory
    ):
        from components.agents.infrastructure.adapters.langchain.memory_service import (
            AgentMemoryService,
        )
        from infrastructure.persistence.ai.agents.models import Agent as AgentORM

        user = user_factory()
        workspace = workspace_factory(owner=user)
        agent_orm = AgentORM.objects.create(
            user=user,
            workspace=workspace,
            agent_type="financial_agent",
        )

        svc = AgentMemoryService(agent_id=str(agent_orm.agent_id))
        svc.add_user_message("create a financial report")
        svc.add_agent_message(
            "I'm generating a PDF financial report you can download.",
            artifacts=[
                {
                    "kind": "financial_report",
                    "id": "report-1",
                    "title": "Q1 Financials",
                    "download_url": "/api/reports/financial-reports/report-1/download/",
                    "mime_type": "application/pdf",
                    "status": "rendering",
                }
            ],
        )

        assistant_msg = ConversationMessage.objects.filter(
            role="assistant"
        ).order_by("-created_at").first()
        assert assistant_msg is not None
        artifacts = assistant_msg.metadata.get("artifacts")
        assert isinstance(artifacts, list)
        assert len(artifacts) == 1
        assert artifacts[0]["kind"] == "financial_report"
        assert artifacts[0]["download_url"].endswith("/download/")

    def test_message_without_artifacts_keeps_empty_metadata(
        self, workspace_factory, user_factory
    ):
        from components.agents.infrastructure.adapters.langchain.memory_service import (
            AgentMemoryService,
        )
        from infrastructure.persistence.ai.agents.models import Agent as AgentORM

        user = user_factory()
        workspace = workspace_factory(owner=user)
        agent_orm = AgentORM.objects.create(
            user=user, workspace=workspace, agent_type="task_agent",
        )

        svc = AgentMemoryService(agent_id=str(agent_orm.agent_id))
        svc.add_agent_message("here is a plain reply with no artifact")

        msg = ConversationMessage.objects.filter(role="assistant").order_by(
            "-created_at"
        ).first()
        assert msg is not None
        # No artifact key at all when none were collected — frontend
        # uses ``metadata.artifacts ?? []`` so absence and empty are
        # equivalent. We don't pollute the JSON with an empty list.
        assert "artifacts" not in msg.metadata


# ── PR-H2 — sponsorship + donation report artifact wiring ──────────────


@pytest.mark.django_db
class TestGenerateSponsorshipReportArtifactWiring:
    """``generate_sponsorship_report`` reuses the existing
    ``FinancialReport`` pipeline with a per-call ``variant`` (impact /
    financial / annual). Default variant is ``impact``. The artifact
    rides on the response message exactly like the financial report.
    """

    def _stub_report(self, report_id="sponsorship-report-1", title="Sponsorship Impact"):
        report = MagicMock()
        report.id = report_id
        report.title = title
        return report

    def test_collects_artifact_with_kind_sponsorship_report(self, sponsorship_chat_agent):
        agent = sponsorship_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            response = generate_sponsorship_report(
                agent,
                {"range_start": "2026-01-01", "range_end": "2026-03-31"},
            )

        assert "PDF sponsorship report" in response
        assert "paperclip" in response
        assert len(agent._pending_artifacts) == 1
        artifact = agent._pending_artifacts[0]
        assert artifact["kind"] == "sponsorship_report"
        assert artifact["id"] == "sponsorship-report-1"
        assert artifact["title"] == "Sponsorship Impact"
        assert artifact["download_url"] == (
            "/api/reports/financial-reports/sponsorship-report-1/download/"
        )
        assert artifact["mime_type"] == "application/pdf"

    def test_defaults_to_impact_variant(self, sponsorship_chat_agent):
        """No ``variant`` in input → impact gets passed through to
        the metrics service. This is the LLM-friendly default Henry
        asked for: 'just default the tool to impact report'."""
        agent = sponsorship_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            generate_sponsorship_report(agent, {})

            service.generate_report.assert_called_once()
            kwargs = service.generate_report.call_args.kwargs
            assert kwargs["metadata"]["variant"] == "impact"

    @pytest.mark.parametrize("variant", ["impact", "financial", "annual"])
    def test_passes_explicit_variant_through(self, sponsorship_chat_agent, variant):
        agent = sponsorship_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            response = generate_sponsorship_report(agent, {"variant": variant})

            assert variant in response
            kwargs = service.generate_report.call_args.kwargs
            assert kwargs["metadata"]["variant"] == variant

    def test_rejects_unknown_variant(self, sponsorship_chat_agent):
        """The LLM occasionally hallucinates variants ('summary',
        'detailed', etc.). Surface the canonical list rather than
        silently coercing — the user gets a clear error and the next
        turn corrects."""
        agent = sponsorship_chat_agent["agent"]

        response = generate_sponsorship_report(
            agent, {"variant": "wat"}
        )

        assert "Invalid variant" in response
        assert "impact" in response and "financial" in response and "annual" in response
        assert agent._pending_artifacts == []


@pytest.mark.django_db
class TestGenerateDonationReportArtifactWiring:
    """``generate_donation_report`` keeps its headline-numbers text
    summary AND attaches a PDF artifact via the same FinancialReport
    pipeline. Default variant is ``impact``.
    """

    def _stub_report(self, report_id="donation-report-1", title="Donation Impact"):
        report = MagicMock()
        report.id = report_id
        report.title = title
        return report

    def test_includes_headline_numbers_and_attaches_artifact(self, donation_chat_agent):
        agent = donation_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            response = generate_donation_report(agent, {})

        assert "Donation Report" in response
        assert "Total Donations:" in response
        assert "paperclip" in response
        assert len(agent._pending_artifacts) == 1
        artifact = agent._pending_artifacts[0]
        assert artifact["kind"] == "donation_report"
        assert artifact["download_url"].startswith("/api/reports/financial-reports/")

    def test_defaults_to_impact_variant(self, donation_chat_agent):
        agent = donation_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            generate_donation_report(agent, {})

            kwargs = service.generate_report.call_args.kwargs
            assert kwargs["metadata"]["variant"] == "impact"

    @pytest.mark.parametrize("variant", ["impact", "financial", "annual"])
    def test_passes_explicit_variant_through(self, donation_chat_agent, variant):
        agent = donation_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            response = generate_donation_report(agent, {"variant": variant})

            assert variant in response
            kwargs = service.generate_report.call_args.kwargs
            assert kwargs["metadata"]["variant"] == variant

    def test_falls_back_to_text_summary_on_pdf_failure(self, donation_chat_agent):
        """If the AI gateway / generation provider blows up, the user
        still gets the headline numbers — we don't hide the summary
        behind a PDF that didn't render."""
        agent = donation_chat_agent["agent"]

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            ProviderCls.return_value.build_generation_service.side_effect = (
                RuntimeError("ai gateway down")
            )

            response = generate_donation_report(agent, {})

        assert "Total Donations:" in response
        assert "PDF attachment unavailable" in response
        assert agent._pending_artifacts == []


# ── Workspace organization report — PR fix 2026-05-09 ───────────────────


@pytest.mark.django_db
class TestGenerateOrganizationReportArtifactWiring:
    """``workspace_agent.generate_organization_report`` was a text-only
    helper before 2026-05-09 — Henry typed "write impact report" in
    chat and got three sentences with no PDF and no paperclip. The
    refactor wires it through the same FinancialReport pipeline as
    every other report tool, so the chat bubble surfaces a paperclip
    download regardless of which agent handled the request.
    """

    def _stub_report(self, report_id="org-report-1", title="Workspace Impact"):
        report = MagicMock()
        report.id = report_id
        report.title = title
        return report

    def test_collects_artifact_with_kind_organization_report(self, workspace_chat_agent):
        agent = workspace_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            response = generate_organization_report(agent, {})

        assert "PDF" in response and "paperclip" in response
        assert len(agent._pending_artifacts) == 1
        artifact = agent._pending_artifacts[0]
        assert artifact["kind"] == "organization_report"
        assert artifact["id"] == "org-report-1"
        assert artifact["download_url"] == (
            "/api/reports/financial-reports/org-report-1/download/"
        )
        assert artifact["mime_type"] == "application/pdf"

    def test_defaults_to_impact_variant(self, workspace_chat_agent):
        """Henry typed 'write impact report' — no variant specified.
        The default must be ``impact`` so the LLM doesn't have to
        clarify subtype before producing the artifact."""
        agent = workspace_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            generate_organization_report(agent, {})

            kwargs = service.generate_report.call_args.kwargs
            assert kwargs["metadata"]["variant"] == "impact"

    @pytest.mark.parametrize("variant", ["impact", "financial", "annual"])
    def test_passes_explicit_variant_through(self, workspace_chat_agent, variant):
        agent = workspace_chat_agent["agent"]
        report = self._stub_report()

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            service = MagicMock()
            service.generate_report.return_value = report
            ProviderCls.return_value.build_generation_service.return_value = service

            response = generate_organization_report(agent, {"variant": variant})

            assert variant in response
            kwargs = service.generate_report.call_args.kwargs
            assert kwargs["metadata"]["variant"] == variant

    def test_rejects_unknown_variant(self, workspace_chat_agent):
        agent = workspace_chat_agent["agent"]

        response = generate_organization_report(agent, {"variant": "wat"})

        assert "Invalid variant" in response
        assert agent._pending_artifacts == []

    def test_returns_friendly_error_when_provider_blows_up(self, workspace_chat_agent):
        """If the AI gateway / generation provider raises, we surface
        a friendly message instead of letting the traceback bubble up
        to the LLM (which would paraphrase it as the next chat
        message)."""
        agent = workspace_chat_agent["agent"]

        with patch(
            "components.reports.application.providers."
            "financial_report_generation_provider."
            "FinancialReportGenerationProvider"
        ) as ProviderCls:
            ProviderCls.return_value.build_generation_service.side_effect = (
                RuntimeError("ai gateway down")
            )

            response = generate_organization_report(agent, {})

        assert "Could not start the impact report" in response
        assert agent._pending_artifacts == []
