import pytest

from infrastructure.persistence.ai.agents.models import Agent
from components.agents.domain.value_objects.plan_schemas import TaskSpec, AssigneeType, Priority
from components.agents.infrastructure.gateways.deep.kanban_sync_service import upsert_task_from_spec


@pytest.mark.django_db(databases=["default"])
def test_upsert_task_persists_description_and_agent_assignee(user_factory, workspace_factory, team_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    agent = Agent.objects.create(agent_type="task_agent", user=owner, workspace=workspace)

    spec = TaskSpec(
        title="Deep task",
        description="Do the thing with context",
        priority=Priority.high,
        workspace_id=str(workspace.id),
        team_id=str(team.id),
        assignee_id=str(agent.agent_id),
        assignee_type=AssigneeType.agent,
    )

    task = upsert_task_from_spec(spec, created_by_id=str(owner.id))

    assert task.assigned_to.filter(id=owner.id).exists()
    assert task.comments.filter(comment="Do the thing with context").exists()
