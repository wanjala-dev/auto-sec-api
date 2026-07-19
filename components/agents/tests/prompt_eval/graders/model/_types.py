"""Shared types for the model-grader registry.

The model grader is an LLM-as-judge that scores subjective quality
axes (tone, instruction-following, completeness, safety) in ONE call
per case. Asking for axes in separate calls would multiply LLM cost
without proportional insight; the LogSeq curriculum and the faura
prompt_eval harness both follow this single-call multi-axis pattern.

Each axis is graded independently — different signals (e.g.
``instruction_following`` dropping while ``completeness`` stays
flat) tell different stories about which dimension a prompt edit
affected.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class AxisScore:
    """One axis's verdict on one test case.

    Per the curriculum's qualitative-before-score rule: the model
    produces ``strengths``, ``weaknesses``, and ``reasoning`` BEFORE
    the numeric score. Without that order the score lazily defaults
    to ~6/10 regardless of plan quality.
    """

    score: int  # 0–10
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass(frozen=True)
class ModelGradeResult:
    """Full multi-axis verdict on one test case.

    ``axes`` is keyed by axis name (e.g. ``"tone"``,
    ``"instruction_following"``, ``"completeness"``, ``"safety"``).
    ``composite_score`` is the unweighted mean across axes — the
    single number the harness pairs with the code-grader score.
    """

    axes: dict[str, AxisScore] = field(default_factory=dict)
    raw_response: str = ""
    error: str = ""

    @property
    def composite_score(self) -> float:
        if not self.axes:
            return 0.0
        return statistics.mean(axis.score for axis in self.axes.values())

    @property
    def is_error(self) -> bool:
        return bool(self.error)

    @property
    def score(self) -> int:
        """Composite score rounded to int.

        Kept as a property for backward-compatibility with reports
        that show ``model_grade.score`` alongside a code-grader score.
        """
        return int(round(self.composite_score))

    @property
    def strengths(self) -> list[str]:
        """Strengths across every axis — for the HTML report's bullets."""
        flat: list[str] = []
        for name, axis in self.axes.items():
            for item in axis.strengths:
                flat.append(f"[{name}] {item}")
        return flat

    @property
    def weaknesses(self) -> list[str]:
        """Weaknesses across every axis — for the HTML report's bullets."""
        flat: list[str] = []
        for name, axis in self.axes.items():
            for item in axis.weaknesses:
                flat.append(f"[{name}] {item}")
        return flat

    @property
    def reasoning(self) -> str:
        """Concatenated reasoning, axis-tagged. For the HTML report."""
        parts = [
            f"{name}: {axis.reasoning}".strip()
            for name, axis in self.axes.items()
            if axis.reasoning
        ]
        return " | ".join(parts)


class ModelGrader(Protocol):
    """A model grader is callable with (case, plan_payload) → result."""

    def __call__(
        self, case: dict[str, Any], plan_payload: dict[str, Any]
    ) -> ModelGradeResult: ...


__all__ = [
    "AxisScore",
    "ModelGradeResult",
    "ModelGrader",
]
