"""Routing grader — the first task's ``agent_type`` matches the expected one.

Test cases with ``expected_agent_type=None`` are split-domain or
open-ended; this grader skips them with a passing score so the
overall average isn't penalised for cases where multiple routes
are legitimate. The model grader handles those nuanced cases.
"""
from __future__ import annotations

from typing import Any

from components.agents.domain.value_objects.plan_schemas import PlanSpec
from components.agents.tests.prompt_eval.graders.code._types import (
    CodeGradeResult,
)


def grade(plan: PlanSpec | None, case: dict[str, Any]) -> CodeGradeResult:
    expected = case.get("expected_agent_type")
    if expected is None:
        return CodeGradeResult(label="agent-type-routing", score=10, reasons=[])
    if plan is None or not plan.tasks:
        return CodeGradeResult(
            label="agent-type-routing",
            score=0,
            reasons=["no plan/tasks to inspect agent_type on"],
        )
    actual = getattr(plan.tasks[0], "agent_type", "") or ""
    if actual == expected:
        return CodeGradeResult(label="agent-type-routing", score=10, reasons=[])
    return CodeGradeResult(
        label="agent-type-routing",
        score=0,
        reasons=[
            f"first task's agent_type is {actual!r}; expected {expected!r}"
        ],
    )
