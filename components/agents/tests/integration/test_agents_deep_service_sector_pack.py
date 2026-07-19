"""Tests for sector-aware deep-pack planning helpers."""
from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep import packs as deep_packs
from components.agents.infrastructure.services import deep_service
from components.agents.infrastructure.adapters.langchain.deep.packs import DeepPack, register_deep_pack
from components.agents.domain.value_objects.plan_schemas import PlanSpec
from infrastructure.persistence.sectors.models import Sector


@pytest.mark.django_db
def test_plan_and_run_with_llm_prefers_sector_pack(monkeypatch, workspace_factory, user_factory):
    """Sector config should override caller-provided deep pack when planning."""
    owner = user_factory()
    sector, _ = Sector.objects.update_or_create(
        slug="education",
        defaults={"name": "Education", "config": {"deep_pack": "initiative_education"}},
    )
    workspace = workspace_factory(owner=owner, sector=sector)
    captured = {}
    monkeypatch.setattr(deep_packs, "_PACK_REGISTRY", {})

    def _fake_plan_planner(**kwargs):
        captured["sector_slug"] = kwargs.get("sector_slug")
        captured["deep_pack"] = kwargs.get("deep_pack")
        captured["context"] = kwargs.get("extra_context") or {}
        return PlanSpec(plan_id=kwargs["plan_id"], goal=kwargs["goal"], tasks=[])

    def _fake_executor(**kwargs):
        captured["executor_plan"] = kwargs.get("plan")
        return {"status": "ok"}

    register_deep_pack(
        DeepPack(
            slug="initiative_education",
            description="Test pack",
            plan_planner=_fake_plan_planner,
            project_planner=_fake_plan_planner,
            executor=_fake_executor,
        )
    )

    deep_service.plan_and_run_with_llm(
        goal="Plan an education initiative",
        plan_id="plan-edu-1",
        agent_type="task_agent",
        user_id=str(owner.id),
        workspace_id=str(workspace.id),
        deep_pack="initiative_override",
        extra_context={"signal": "value"},
    )

    assert captured["sector_slug"] == "education"
    assert captured["deep_pack"] == "initiative_education"
    assert captured["context"]["deep_pack"] == "initiative_education"
    assert captured["context"]["sector"] == "education"
    assert captured["context"]["signal"] == "value"


@pytest.mark.django_db
def test_plan_and_create_project_includes_sector_pack(monkeypatch, workspace_factory, user_factory):
    """Project planning should inherit sector deep-pack context."""
    owner = user_factory()
    sector, _ = Sector.objects.update_or_create(
        slug="healthcare",
        defaults={"name": "Healthcare", "config": {"deep_pack": "initiative_healthcare"}},
    )
    workspace = workspace_factory(owner=owner, sector=sector)
    captured = {}
    monkeypatch.setattr(deep_packs, "_PACK_REGISTRY", {})

    def _fake_project_planner(**kwargs):
        captured["sector_slug"] = kwargs.get("sector_slug")
        captured["deep_pack"] = kwargs.get("deep_pack")
        captured["context"] = kwargs.get("extra_context") or {}
        return PlanSpec(plan_id=kwargs["plan_id"], goal=kwargs["goal"], tasks=[])

    register_deep_pack(
        DeepPack(
            slug="initiative_healthcare",
            description="Test pack",
            plan_planner=_fake_project_planner,
            project_planner=_fake_project_planner,
            executor=lambda **kwargs: {"status": "noop"},
        )
    )
    monkeypatch.setattr(
        deep_service,
        "run_project_creation",
        lambda **kwargs: {
            "project_id": "proj-1",
            "task_ids": [],
            "estimate_ids": [],
            "transaction_ids": [],
            "estimated_total": "0",
            "summary": "ok",
        },
    )

    result = deep_service.plan_and_create_project(
        goal="Launch a health outreach project",
        plan_id="plan-health-1",
        project_title="Health Outreach",
        user_id=str(owner.id),
        workspace_id=str(workspace.id),
    )

    assert result["status"] == "completed"
    assert captured["sector_slug"] == "healthcare"
    assert captured["deep_pack"] == "initiative_healthcare"
    assert captured["context"]["deep_pack"] == "initiative_healthcare"
    assert captured["context"]["sector"] == "healthcare"
