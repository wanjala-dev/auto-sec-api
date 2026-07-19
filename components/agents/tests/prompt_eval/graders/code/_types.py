"""Shared types for the code grader registry.

Lives in ``_types`` (underscore prefix) so it's clear this is the
shared vocabulary, not a grader itself. Pytest collects from
``test_*.py`` files only, so this name does not interfere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from components.agents.domain.value_objects.plan_schemas import PlanSpec


@dataclass(frozen=True)
class CodeGradeResult:
    """One code-grader's verdict on one test case.

    ``score`` is 0–10 (10 = passes every check). ``reasons`` is empty
    when the score is 10; otherwise it contains one short string per
    failed check so the HTML report can show why.
    """

    label: str
    score: int
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score == 10


@dataclass(frozen=True)
class AggregateCodeGrade:
    """The full code-grader verdict for one test case."""

    overall_score: float
    sub_scores: list[CodeGradeResult]

    def reasons_flat(self) -> list[str]:
        flat: list[str] = []
        for sub in self.sub_scores:
            for reason in sub.reasons:
                flat.append(f"[{sub.label}] {reason}")
        return flat


# A code grader is a callable that scores one plan in the context of
# one case. Case is the raw dict from the dataset (so the grader can
# read ``expected_agent_type``, ``criteria``, or other fields).
CodeGrader = Callable[[PlanSpec | None, dict[str, Any]], CodeGradeResult]


__all__ = [
    "AggregateCodeGrade",
    "CodeGradeResult",
    "CodeGrader",
]
