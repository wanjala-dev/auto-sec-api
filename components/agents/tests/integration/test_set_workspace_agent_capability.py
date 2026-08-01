"""Integration tests — workspace-level triage-agent capability toggle (ADR 0010).

The setter half of the draft-PR gate: an owner enables/disables
``open_draft_pr`` on the workspace's ``triage_agent`` row. Covers the
ensure-if-missing on a fresh org, the flip actually landing on
``config.capabilities``, the allowlist, and — the integration that matters —
that ``OpenDraftPrUseCase._require_capability`` PASSES after enable and RAISES
``capability_disabled`` after disable.
"""

from __future__ import annotations

import pytest

from components.agents.application.service import AgentsService
from components.agents.application.use_cases.set_workspace_agent_capability_use_case import (
    SetWorkspaceAgentCapabilityUseCase,
    get_workspace_capabilities,
)
from components.shared_kernel.domain.errors import NotFoundError, ValidationError


def _triage_rows(workspace):
    from infrastructure.persistence.ai.agents.models import Agent

    return Agent.objects.filter(workspace=workspace, agent_type="triage_agent")


@pytest.mark.django_db
class TestSetWorkspaceAgentCapability:
    def test_enable_on_fresh_workspace_creates_row_and_sets_flag(self, workspace_factory):
        ws = workspace_factory()
        assert not _triage_rows(ws).exists()

        result = SetWorkspaceAgentCapabilityUseCase().execute(
            workspace_id=str(ws.id), capability="open_draft_pr", enabled=True, actor=ws.workspace_owner
        )

        assert result.created is True
        assert result.capabilities["open_draft_pr"] is True
        row = _triage_rows(ws).get()
        assert row.config["capabilities"]["open_draft_pr"] is True

    def test_enable_then_disable_flips_config(self, workspace_factory):
        ws = workspace_factory()
        uc = SetWorkspaceAgentCapabilityUseCase()

        uc.execute(workspace_id=str(ws.id), capability="open_draft_pr", enabled=True, actor=ws.workspace_owner)
        result = uc.execute(
            workspace_id=str(ws.id), capability="open_draft_pr", enabled=False, actor=ws.workspace_owner
        )

        assert result.created is False  # second call reuses the ensured row
        assert result.capabilities["open_draft_pr"] is False
        assert _triage_rows(ws).count() == 1  # never a duplicate row
        assert _triage_rows(ws).get().config["capabilities"]["open_draft_pr"] is False

    def test_reuses_existing_triage_row(self, workspace_factory):
        from infrastructure.persistence.ai.agents.models import Agent

        ws = workspace_factory()
        existing = Agent.objects.create(
            workspace=ws, user=ws.workspace_owner, agent_type="triage_agent", config={"custom": {"x": 1}}
        )
        SetWorkspaceAgentCapabilityUseCase().execute(
            workspace_id=str(ws.id), capability="open_draft_pr", enabled=True, actor=ws.workspace_owner
        )
        existing.refresh_from_db()
        # Merged, not clobbered.
        assert existing.config["custom"] == {"x": 1}
        assert existing.config["capabilities"]["open_draft_pr"] is True
        assert _triage_rows(ws).count() == 1

    def test_unknown_capability_rejected(self, workspace_factory):
        ws = workspace_factory()
        with pytest.raises(ValidationError):
            SetWorkspaceAgentCapabilityUseCase().execute(
                workspace_id=str(ws.id), capability="delete_everything", enabled=True, actor=ws.workspace_owner
            )
        assert not _triage_rows(ws).exists()  # nothing provisioned for a bad key

    def test_missing_workspace_raises_not_found(self, db):
        with pytest.raises(NotFoundError):
            SetWorkspaceAgentCapabilityUseCase().execute(
                workspace_id="00000000-0000-0000-0000-000000000000",
                capability="open_draft_pr",
                enabled=True,
                actor=None,
            )

    def test_read_reports_false_when_no_row(self, workspace_factory):
        ws = workspace_factory()
        result = get_workspace_capabilities(str(ws.id))
        assert result.capabilities == {"open_draft_pr": False}
        assert not _triage_rows(ws).exists()  # read never provisions

    def test_service_wrapper_enable_and_read(self, workspace_factory):
        ws = workspace_factory()
        AgentsService().set_workspace_agent_capability(
            workspace_id=str(ws.id), capability="open_draft_pr", enabled=True, actor=ws.workspace_owner
        )
        state = AgentsService().workspace_agent_capabilities(workspace_id=str(ws.id))
        assert state.capabilities["open_draft_pr"] is True


@pytest.mark.django_db
class TestGateHonoursToggle:
    """The whole point: the toggle drives ``OpenDraftPrUseCase._require_capability``."""

    def test_gate_passes_after_enable_and_raises_after_disable(self, workspace_factory):
        from components.integrations.application.use_cases.open_draft_pr_use_case import (
            DraftPrPreconditionError,
            OpenDraftPrUseCase,
        )

        ws = workspace_factory()
        uc = OpenDraftPrUseCase(adapter_factory=lambda provider, token: None)

        # Disabled (no row): the gate refuses.
        with pytest.raises(DraftPrPreconditionError) as exc:
            uc._require_capability(str(ws.id))
        assert exc.value.reason == "capability_disabled"

        # Enable → gate passes (no exception).
        SetWorkspaceAgentCapabilityUseCase().execute(
            workspace_id=str(ws.id), capability="open_draft_pr", enabled=True, actor=ws.workspace_owner
        )
        uc._require_capability(str(ws.id))  # must not raise

        # Disable → gate refuses again.
        SetWorkspaceAgentCapabilityUseCase().execute(
            workspace_id=str(ws.id), capability="open_draft_pr", enabled=False, actor=ws.workspace_owner
        )
        with pytest.raises(DraftPrPreconditionError) as exc2:
            uc._require_capability(str(ws.id))
        assert exc2.value.reason == "capability_disabled"
