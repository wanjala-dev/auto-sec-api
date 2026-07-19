"""Banned-words grader — enforces project domain conventions.

This product's domain language uses ``recipient`` rather than
``child``. It's a project-wide convention worth enforcing
deterministically — a model grader sometimes lets ``child`` slip
through because it's grammatically natural. Add new banned/preferred
pairs to ``BANNED_WORD_RULES`` as they emerge.
"""
from __future__ import annotations

import re
from typing import Any

from components.agents.domain.value_objects.plan_schemas import PlanSpec
from components.agents.tests.prompt_eval.graders.code._types import (
    CodeGradeResult,
)


# Word pairs the project enforces. Each tuple is
# ``(banned, preferred, why)``. Add more as they emerge.
BANNED_WORD_RULES: tuple[tuple[str, str, str], ...] = (
    ("child", "recipient", "workspace beneficiary-language convention"),
    ("children", "recipients", "workspace beneficiary-language convention"),
)


def grade(plan: PlanSpec | None, case: dict[str, Any]) -> CodeGradeResult:  # noqa: ARG001
    reasons: list[str] = []
    if plan is None or not plan.tasks:
        return CodeGradeResult(label="no-banned-words", score=10, reasons=[])

    for task in plan.tasks:
        text = " ".join(
            filter(
                None,
                [
                    getattr(task, "title", "") or "",
                    getattr(task, "description", "") or "",
                ],
            )
        ).lower()
        for banned, prefer, _why in BANNED_WORD_RULES:
            # Word-boundary check so 'children' still hits but
            # 'attached' does not match 'ed'.
            if re.search(rf"\b{re.escape(banned)}\b", text):
                reasons.append(
                    f"task uses banned word {banned!r} — prefer {prefer!r} per "
                    "project domain conventions"
                )
                break

    score = 10 if not reasons else max(0, 10 - 3 * len(reasons))
    return CodeGradeResult(
        label="no-banned-words",
        score=score,
        reasons=reasons,
    )
