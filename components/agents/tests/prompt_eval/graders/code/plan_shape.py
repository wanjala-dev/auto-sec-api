"""Plan-shape grader — non-None plan, non-empty tasks, required fields.

Per the planner system prompt: an empty ``tasks`` array is never
acceptable. This is the deterministic floor for that invariant —
a plan that fails it can't have scored well on any other axis.
"""
from __future__ import annotations

from typing import Any

from components.agents.domain.value_objects.plan_schemas import PlanSpec
from components.agents.tests.prompt_eval.graders.code._types import (
    CodeGradeResult,
)


def grade(plan: PlanSpec | None, case: dict[str, Any]) -> CodeGradeResult:  # noqa: ARG001
    """Plan must be non-None, have ≥1 task, every task carries required fields."""
    if plan is None:
        return CodeGradeResult(
            label="plan-shape",
            score=0,
            reasons=["plan is None — planner returned no PlanSpec at all"],
        )
    if not plan.tasks:
        return CodeGradeResult(
            label="plan-shape",
            score=0,
            reasons=["plan.tasks is empty — every goal must produce at least one task"],
        )
    reasons: list[str] = []
    for index, task in enumerate(plan.tasks):
        if not getattr(task, "title", "").strip():
            reasons.append(f"task[{index}] has empty title")
        if not getattr(task, "agent_type", "").strip():
            reasons.append(f"task[{index}] has empty agent_type")
    score = 10 if not reasons else max(0, 10 - 2 * len(reasons))
    return CodeGradeResult(label="plan-shape", score=score, reasons=reasons)
