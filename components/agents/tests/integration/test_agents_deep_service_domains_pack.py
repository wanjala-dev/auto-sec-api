"""Deep-service planner context carries the workspace's security domains.

Replaces the wanjala-era sector-pack test (which imported the deleted
``infrastructure.persistence.sectors`` app). Domains are pure classification
— the M2M carries no config, so the caller-provided deep pack always stands
and the planner receives the domain slugs as grounding context.
"""

from __future__ import annotations

import pytest

from components.agents.domain.value_objects.plan_schemas import PlanSpec
from components.agents.infrastructure.adapters.langchain.deep import packs as deep_packs
from components.agents.infrastructure.adapters.langchain.deep.packs import DeepPack, register_deep_pack
from components.agents.infrastructure.services import deep_service
from infrastructure.persistence.domains.models import Domain


def _register_capture_pack(monkeypatch, captured, slug="default"):
    monkeypatch.setattr(deep_packs, "_PACK_REGISTRY", {})

    def _fake_plan_planner(**kwargs):
        captured["domain_slugs"] = kwargs.get("domain_slugs")
        captured["deep_pack"] = kwargs.get("deep_pack")
        captured["context"] = kwargs.get("extra_context") or {}
        return PlanSpec(plan_id=kwargs["plan_id"], goal=kwargs["goal"], tasks=[])

    def _fake_executor(**kwargs):
        captured["executor_plan"] = kwargs.get("plan")
        return {"status": "ok"}

    register_deep_pack(
        DeepPack(
            slug=slug,
            description="Test pack",
            plan_planner=_fake_plan_planner,
            project_planner=_fake_plan_planner,
            executor=_fake_executor,
        )
    )


@pytest.mark.django_db
def test_planner_receives_workspace_domain_slugs(monkeypatch, workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    cloud, _ = Domain.objects.get_or_create(slug="cloud", defaults={"name": "Cloud"})
    endpoint, _ = Domain.objects.get_or_create(slug="endpoint", defaults={"name": "Endpoint"})
    workspace.domains.add(cloud, endpoint)

    captured = {}
    # No deep_pack arg → get_deep_pack(None) falls back to the default slug;
    # the capture pack must be registered under it to be picked up.
    _register_capture_pack(monkeypatch, captured, slug=deep_packs.DEFAULT_PACK_SLUG)

    deep_service.plan_and_run_with_llm(
        goal="Sweep cloud logs",
        plan_id="plan-dom-1",
        agent_type="task_agent",
        user_id=str(owner.id),
        workspace_id=str(workspace.id),
        extra_context={"signal": "value"},
    )

    assert sorted(captured["domain_slugs"]) == ["cloud", "endpoint"]
    assert sorted(captured["context"]["domains"]) == ["cloud", "endpoint"]
    assert captured["context"]["signal"] == "value"


@pytest.mark.django_db
def test_caller_deep_pack_stands_and_no_domains_is_fine(monkeypatch, workspace_factory, user_factory):
    """No domains tagged → empty slugs, no 'domains' context key, pack passthrough."""
    owner = user_factory()
    workspace = workspace_factory(owner=owner)

    captured = {}
    _register_capture_pack(monkeypatch, captured, slug="soc_default")

    deep_service.plan_and_run_with_llm(
        goal="Triage findings",
        plan_id="plan-dom-2",
        agent_type="task_agent",
        user_id=str(owner.id),
        workspace_id=str(workspace.id),
        deep_pack="soc_default",
    )

    assert captured["domain_slugs"] == ()
    assert "domains" not in captured["context"]
    assert captured["deep_pack"] == "soc_default"
