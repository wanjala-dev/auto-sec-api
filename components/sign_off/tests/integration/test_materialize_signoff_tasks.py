"""Integration tests: sign-off queue → AI-team Kanban projection (Phase 6b).

Exercises ``materialize_signoff_tasks`` end-to-end against the real Agents
board (team / project / columns) using an in-memory ``FakeSignOffAdapter``
registered on a fresh ``SignOffRegistry`` (one fake per port, per the
testing skill). Proves:

* a pending item becomes a card on the "Suggested" column, assigned to the
  workspace owner, carrying the artifact ref + risk band + receipts in
  ``metadata.context``;
* the projection is idempotent (same idempotency key → no duplicate);
* reconcile moves a card whose artifact is no longer pending to the terminal
  column matching its final review state (approved → Accepted, rejected →
  Dismissed).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from components.sign_off.application.providers.sign_off_registry_provider import (
    SignOffRegistry,
)
from components.sign_off.application.services.materialize_signoff_tasks import (
    SIGN_OFF_SOURCE_TYPE,
    materialize_all_pending_signoff_tasks,
    materialize_workspace_signoff_tasks,
)
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.risk_band import RiskBand
from components.sign_off.domain.value_objects.sign_off_item import (
    ReceiptsSummary,
    SignOffItem,
)
from components.sign_off.tests.unit.fakes import FakeSignOffAdapter


ARTIFACT_TYPE = "report"
ARTIFACT_ID = "artifact-1"


def _item(workspace_id: str, *, risk_band: RiskBand = RiskBand.AMBER) -> SignOffItem:
    return SignOffItem(
        artifact_type=ARTIFACT_TYPE,
        artifact_id=ARTIFACT_ID,
        title="June Impact Report",
        review_state=ReviewState.PENDING,
        risk_band=risk_band,
        audience="external",
        receipts_summary=ReceiptsSummary(
            unverified_figures=2, ungrounded_claims=1, voice_flags=0, is_clean=False
        ),
        workspace_id=workspace_id,
        created_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
    )


def _registry_with(adapter: FakeSignOffAdapter) -> SignOffRegistry:
    registry = SignOffRegistry()
    registry.register(adapter)
    return registry


@pytest.mark.django_db
class TestMaterializeWorkspaceSignoffTasks:
    def test_creates_task_on_suggested_assigned_to_owner(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        from components.agents.infrastructure.services.agents_board_service import (
            SUGGESTED,
        )
        from components.agents.application.facades.ai_teammate_facade import (
            ensure_agents_board,
        )

        workspace = workspace_factory()
        adapter = FakeSignOffAdapter(ARTIFACT_TYPE, pending=[_item(str(workspace.id))])

        result = materialize_workspace_signoff_tasks(
            str(workspace.id), registry=_registry_with(adapter)
        )

        assert result["created"] == 1

        task = Task.objects.get(
            workspace=workspace, source_type=SIGN_OFF_SOURCE_TYPE
        )
        # Landed on the Suggested column of the AI Findings board.
        board = ensure_agents_board(workspace)
        assert task.column_id == board.column(SUGGESTED).id
        # Assigned to the workspace owner.
        assert workspace.workspace_owner_id in {
            u.id for u in task.assigned_to.all()
        }
        # Artifact ref + risk band + receipts ride on metadata.context.
        ctx = task.metadata["context"]
        assert ctx["artifact_type"] == ARTIFACT_TYPE
        assert ctx["artifact_id"] == ARTIFACT_ID
        assert ctx["risk_band"] == RiskBand.AMBER.value
        assert ctx["review_state"] == ReviewState.PENDING.value
        assert ctx["receipts_summary"]["unverified_figures"] == 2
        assert task.title == "Review: June Impact Report"

    def test_idempotent_no_duplicate(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        adapter = FakeSignOffAdapter(ARTIFACT_TYPE, pending=[_item(str(workspace.id))])
        registry = _registry_with(adapter)

        materialize_workspace_signoff_tasks(str(workspace.id), registry=registry)
        second = materialize_workspace_signoff_tasks(
            str(workspace.id), registry=registry
        )

        assert second["created"] == 0
        assert (
            Task.objects.filter(
                workspace=workspace, source_type=SIGN_OFF_SOURCE_TYPE
            ).count()
            == 1
        )

    def test_reconcile_approved_moves_to_accepted(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        from components.agents.application.facades.ai_teammate_facade import (
            ensure_agents_board,
        )
        from components.agents.infrastructure.services.agents_board_service import (
            ACCEPTED,
        )

        workspace = workspace_factory()

        # Run 1: item pending → card on Suggested.
        pending_adapter = FakeSignOffAdapter(
            ARTIFACT_TYPE, pending=[_item(str(workspace.id))]
        )
        materialize_workspace_signoff_tasks(
            str(workspace.id), registry=_registry_with(pending_adapter)
        )

        # Run 2: item no longer pending, artifact now APPROVED.
        approved_adapter = FakeSignOffAdapter(
            ARTIFACT_TYPE, pending=[], state=ReviewState.APPROVED
        )
        result = materialize_workspace_signoff_tasks(
            str(workspace.id), registry=_registry_with(approved_adapter)
        )

        assert result["reconciled_accepted"] == 1
        board = ensure_agents_board(workspace)
        task = Task.objects.get(
            workspace=workspace, source_type=SIGN_OFF_SOURCE_TYPE
        )
        assert task.column_id == board.column(ACCEPTED).id
        assert task.status == Task.DONE

    def test_reconcile_rejected_moves_to_dismissed(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        from components.agents.application.facades.ai_teammate_facade import (
            ensure_agents_board,
        )
        from components.agents.infrastructure.services.agents_board_service import (
            DISMISSED,
        )

        workspace = workspace_factory()

        pending_adapter = FakeSignOffAdapter(
            ARTIFACT_TYPE, pending=[_item(str(workspace.id))]
        )
        materialize_workspace_signoff_tasks(
            str(workspace.id), registry=_registry_with(pending_adapter)
        )

        rejected_adapter = FakeSignOffAdapter(
            ARTIFACT_TYPE, pending=[], state=ReviewState.REJECTED
        )
        result = materialize_workspace_signoff_tasks(
            str(workspace.id), registry=_registry_with(rejected_adapter)
        )

        assert result["reconciled_dismissed"] == 1
        board = ensure_agents_board(workspace)
        task = Task.objects.get(
            workspace=workspace, source_type=SIGN_OFF_SOURCE_TYPE
        )
        assert task.column_id == board.column(DISMISSED).id
        assert task.status == Task.ARCHIVED

    def test_reconcile_idempotent_when_already_terminal(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()

        materialize_workspace_signoff_tasks(
            str(workspace.id),
            registry=_registry_with(
                FakeSignOffAdapter(ARTIFACT_TYPE, pending=[_item(str(workspace.id))])
            ),
        )
        approved_registry = _registry_with(
            FakeSignOffAdapter(ARTIFACT_TYPE, pending=[], state=ReviewState.APPROVED)
        )
        materialize_workspace_signoff_tasks(
            str(workspace.id), registry=approved_registry
        )
        # Second reconcile pass — card already Accepted → no re-move.
        again = materialize_workspace_signoff_tasks(
            str(workspace.id), registry=approved_registry
        )
        assert again["reconciled_accepted"] == 0
        assert (
            Task.objects.filter(
                workspace=workspace, source_type=SIGN_OFF_SOURCE_TYPE
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestMaterializeSweep:
    def test_sweep_covers_workspace_with_agents_team(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        from components.agents.application.facades.ai_teammate_facade import (
            ensure_agents_board,
        )

        workspace = workspace_factory()
        # Provision the Agents team so the sweep's Team query finds it.
        ensure_agents_board(workspace)

        adapter = FakeSignOffAdapter(ARTIFACT_TYPE, pending=[_item(str(workspace.id))])
        totals = materialize_all_pending_signoff_tasks(
            registry=_registry_with(adapter)
        )

        assert totals["workspaces"] >= 1
        assert totals["created"] >= 1
        assert Task.objects.filter(
            workspace=workspace, source_type=SIGN_OFF_SOURCE_TYPE
        ).exists()
