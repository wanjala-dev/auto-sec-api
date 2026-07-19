"""JSON-validity grader — verifies the planner produced a structurally usable shape.

A plan that survives the parse but fails this check usually has a
title or description field that lost its structure during JSON repair.
Catches edge cases the plan-shape grader's existence checks miss
(e.g., title is a list of fragments, description is a nested object).

Run after plan-shape so plan-shape's `plan is None` reason is the
clearer signal; this grader assumes a plan exists and inspects the
field *types*.
"""
from __future__ import annotations

from typing import Any

from components.agents.domain.value_objects.plan_schemas import PlanSpec
from components.agents.tests.prompt_eval.graders.code._types import (
    CodeGradeResult,
)


def grade(plan: PlanSpec | None, case: dict[str, Any]) -> CodeGradeResult:  # noqa: ARG001
    if plan is None or not plan.tasks:
        # Plan-shape grader will already have called this out.
        return CodeGradeResult(label="json-validity", score=10, reasons=[])
    reasons: list[str] = []
    for index, task in enumerate(plan.tasks):
        title = getattr(task, "title", None)
        description = getattr(task, "description", None)
        agent_type = getattr(task, "agent_type", None)
        if title is not None and not isinstance(title, str):
            reasons.append(
                f"task[{index}].title is not a string ({type(title).__name__})"
            )
        if description is not None and not isinstance(description, str):
            reasons.append(
                f"task[{index}].description is not a string "
                f"({type(description).__name__})"
            )
        if agent_type is not None and not isinstance(agent_type, str):
            reasons.append(
                f"task[{index}].agent_type is not a string "
                f"({type(agent_type).__name__})"
            )
    score = 10 if not reasons else max(0, 10 - 2 * len(reasons))
    return CodeGradeResult(label="json-validity", score=score, reasons=reasons)
