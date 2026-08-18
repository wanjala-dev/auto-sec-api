"""The specialist move keeps team/project/column consistent (ADR 0030 P3, QA F1).

Pre-P3, ``process_pending_finding`` moved a handled card to the TEAM board's
lazily-created Triage/Optimize column while the card kept
``project = "AI Findings"`` — a column belonging to no project under a task
claiming one. The card vanished from the board the operator was watching.

P3 pins, via the shared choreography (exercised through the deterministic
``triage_cloud_exposure`` specialist so no LLM is involved):

* the handled card moves to the canonical **In Progress** lane on the card's
  OWN board — its project's board when it has one, the team board otherwise;
* ``team`` / ``project`` / ``column`` are derived from the destination column
  together (MoveTaskToBoardView semantics) — the F1 class is impossible by
  construction;
* ``workflow_status`` mirrors the destination lane (the P1 sync bridge's
  ``update_fields`` trap fix covers this exact partial save);
* no bespoke Triage/Optimize lane is minted anymore.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import triage_agent as triage_tools
from components.project.domain.workflow_status_vocabulary import CATEGORY_STARTED
from infrastructure.persistence.project.models import Column, Project, Task

_CLOUD_SOURCE = "ai.cloud_exposure"

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _agent(workspace, owner):
    return SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id))


def _cloud_metadata():
    return {
        "agent_type": "triage_agent",
        "triage": {"status": "pending"},
        "payload": {
            "lookup_key": "attack_path:test",
            "signal": "Public aws_ec2_instance 'web-frontend' can reach AdministratorAccess",
            "confidence": "high",
            "severity": "critical",
            "category": "public_compute_admin",
            "entry": "web-frontend",
            "target": "AdministratorAccess",
            "evidence": ["web-frontend → app-exec-role → AdministratorAccess"],
        },
    }


def _project_board(workspace_factory, team_factory):
    """The one-surface world: an AI Findings project with a canonical intake lane."""
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    project = Project.objects.create(workspace=workspace, team=team, title="AI Findings", created_by=owner)
    intake = Column.objects.create(
        team=team, workspace=workspace, project=project, title="Todo", order=2, created_by=owner
    )
    return workspace, owner, team, project, intake


class TestSpecialistMoveFkConsistency:
    def test_handled_card_moves_to_in_progress_on_its_own_project_board(self, workspace_factory, team_factory):
        workspace, owner, team, project, intake = _project_board(workspace_factory, team_factory)
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            project=project,
            column=intake,
            created_by=owner,
            title="Critical: attack path",
            source_type=_CLOUD_SOURCE,
            metadata=_cloud_metadata(),
        )

        result = triage_tools.triage_cloud_exposure(_agent(workspace, owner), str(task.id))

        assert "Handled" in result
        task.refresh_from_db()
        assert task.column is not None
        assert task.column.title == "In Progress"
        # The three FKs are consistent — derived from the destination column.
        assert task.column.project_id == project.id
        assert task.project_id == project.id
        assert task.column.team_id == team.id
        assert task.team_id == team.id
        # The AI state is the chip, not the lane.
        assert task.metadata["triage"]["status"] == "triaged"

    def test_move_sets_workflow_status_despite_partial_update_fields(self, workspace_factory, team_factory):
        workspace, owner, team, project, intake = _project_board(workspace_factory, team_factory)
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            project=project,
            column=intake,
            created_by=owner,
            title="Critical: attack path",
            source_type=_CLOUD_SOURCE,
            metadata=_cloud_metadata(),
        )

        triage_tools.triage_cloud_exposure(_agent(workspace, owner), str(task.id))

        task.refresh_from_db()
        assert task.workflow_status is not None
        assert task.workflow_status.name == "In Progress"
        assert task.workflow_status.category == CATEGORY_STARTED
        assert task.workflow_status_id == task.column.workflow_status_id

    def test_stale_project_card_is_healed_onto_the_project_board(self, workspace_factory, team_factory):
        """A pre-P3-shaped card (project set, column on the team board) lands
        on its project's In Progress lane — the inconsistency self-heals."""
        workspace, owner, team, project, _intake = _project_board(workspace_factory, team_factory)
        stale_team_lane = Column.objects.create(
            team=team, workspace=workspace, project=None, title="Triage", order=7, created_by=owner
        )
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            project=project,  # stale pairing: project set, column project-less
            column=stale_team_lane,
            created_by=owner,
            title="Critical: attack path",
            source_type=_CLOUD_SOURCE,
            metadata=_cloud_metadata(),
        )

        triage_tools.triage_cloud_exposure(_agent(workspace, owner), str(task.id))

        task.refresh_from_db()
        assert task.column.title == "In Progress"
        assert task.column.project_id == project.id
        assert task.project_id == project.id

    def test_projectless_card_moves_within_its_team_board(self, workspace_factory, team_factory):
        """A card with no project stays on the team board — the specialist
        never yanks it onto a project the operator didn't choose."""
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        intake = Column.objects.create(
            team=team, workspace=workspace, project=None, title="Todo", order=2, created_by=owner
        )
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            project=None,
            column=intake,
            created_by=owner,
            title="Critical: attack path",
            source_type=_CLOUD_SOURCE,
            metadata=_cloud_metadata(),
        )

        triage_tools.triage_cloud_exposure(_agent(workspace, owner), str(task.id))

        task.refresh_from_db()
        assert task.column.title == "In Progress"
        assert task.column.project_id is None
        assert task.project_id is None
        assert task.column.team_id == team.id

    def test_no_bespoke_triage_or_optimize_lane_is_minted(self, workspace_factory, team_factory):
        workspace, owner, team, project, intake = _project_board(workspace_factory, team_factory)
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            project=project,
            column=intake,
            created_by=owner,
            title="Critical: attack path",
            source_type=_CLOUD_SOURCE,
            metadata=_cloud_metadata(),
        )

        triage_tools.triage_cloud_exposure(_agent(workspace, owner), str(task.id))

        assert not Column.objects.filter(team=team, workspace=workspace, title__in=["Triage", "Optimize"]).exists()
