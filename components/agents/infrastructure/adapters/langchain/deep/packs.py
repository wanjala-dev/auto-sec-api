"""
Deep-pack registry for sector-aware planning/execution.

Deep packs let us route planning and execution through sector-specific
planners/graphs while keeping a stable default fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .llm_planner import plan_with_llm, plan_project_with_llm
from .runner import execute_plan_once
from components.agents.domain.value_objects.plan_schemas import PlanSpec, PlanState

PlanPlanner = Callable[..., PlanSpec]
PlanExecutor = Callable[..., PlanState]


@dataclass(frozen=True)
class DeepPack:
    slug: str
    description: str
    plan_planner: PlanPlanner
    project_planner: PlanPlanner
    executor: PlanExecutor


DEFAULT_PACK_SLUG = "initiative_nonprofit"
_PACK_REGISTRY: Dict[str, DeepPack] = {}


def register_deep_pack(pack: DeepPack) -> None:
    _PACK_REGISTRY[pack.slug] = pack


def get_deep_pack(slug: Optional[str]) -> DeepPack:
    if not _PACK_REGISTRY:
        _register_default_packs()
    if slug and slug in _PACK_REGISTRY:
        return _PACK_REGISTRY[slug]
    return _PACK_REGISTRY[DEFAULT_PACK_SLUG]


def _register_default_packs() -> None:
    base_pack = DeepPack(
        slug=DEFAULT_PACK_SLUG,
        description="Default deep pack for nonprofit planning/execution.",
        plan_planner=plan_with_llm,
        project_planner=plan_project_with_llm,
        executor=execute_plan_once,
    )
    register_deep_pack(base_pack)
    for slug in ("initiative_education", "initiative_healthcare", "initiative_pharma"):
        register_deep_pack(
            DeepPack(
                slug=slug,
                description=f"Default deep pack scaffold for {slug.replace('initiative_', '')}.",
                plan_planner=plan_with_llm,
                project_planner=plan_project_with_llm,
                executor=execute_plan_once,
            )
        )
