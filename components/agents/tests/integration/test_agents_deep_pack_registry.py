import uuid

import pytest

from components.agents.infrastructure.adapters.langchain.deep.packs import DeepPack, register_deep_pack
from components.agents.domain.value_objects.plan_schemas import PlanSpec
from components.agents.infrastructure.services.deep_service import plan_and_run_with_llm
from infrastructure.persistence.sectors.models import Sector
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.users.models import CustomUser


@pytest.mark.django_db
def test_plan_and_run_uses_registered_pack_executor():
    captured = {}
    pack_slug = f"initiative_test_{uuid.uuid4().hex[:8]}"

    def planner(**kwargs):
        captured["planner"] = kwargs
        return PlanSpec(plan_id=kwargs["plan_id"], goal=kwargs["goal"], tasks=[])

    def executor(**kwargs):
        captured["executor"] = kwargs
        return {"final_output": {"pack": pack_slug}}

    register_deep_pack(
        DeepPack(
            slug=pack_slug,
            description="Test pack",
            plan_planner=planner,
            project_planner=planner,
            executor=executor,
        )
    )

    sector = Sector.objects.create(slug=f"sector-{uuid.uuid4().hex[:6]}", name="Test Sector", config={"deep_pack": pack_slug})
    user = CustomUser.objects.create_user(username="testuser", email="test@example.com", password="pw12345")
    workspace = Workspace.objects.create(workspace_name="Test Workspace", workspace_owner=user, sector=sector, status="active")

    state = plan_and_run_with_llm(
        goal="Test deep pack",
        plan_id=str(uuid.uuid4()),
        agent_type="task_agent",
        user_id=str(user.id),
        workspace_id=str(workspace.id),
        team_id=None,
        agent_config={},
        model_name=None,
        sync_to_kanban=False,
        extra_context=None,
        deep_pack=None,
    )

    assert state["final_output"]["pack"] == pack_slug
    assert captured["planner"]["deep_pack"] == pack_slug
    assert captured["executor"]["agent_type"] == "task_agent"
