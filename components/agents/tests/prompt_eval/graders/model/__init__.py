"""Model-grader registry.

Each model grader is an LLM-as-judge for one prompt set. A grader
returns a :class:`ModelGradeResult` whose ``composite_score`` is the
mean of its per-axis scores (faura/prompt_eval's pattern — same
LLM call, multi-axis response, per-axis trend lines).

Adding a new model grader:

1. Create ``<grader_name>.py`` with a callable that takes
   ``(case, plan_payload)`` and returns ``ModelGradeResult``.
2. Append the instance (or a default) to the module's ``__all__``.
3. The runner picks the right grader per prompt set.
"""
from __future__ import annotations

from components.agents.tests.prompt_eval.graders.model._types import (
    AxisScore,
    ModelGradeResult,
    ModelGrader,
)
from components.agents.tests.prompt_eval.graders.model.planner_judge import (
    DEFAULT_PLANNER_JUDGE,
    GRADER_SYSTEM_PROMPT,
    PlannerJudge,
)


__all__ = [
    "AxisScore",
    "DEFAULT_PLANNER_JUDGE",
    "GRADER_SYSTEM_PROMPT",
    "ModelGradeResult",
    "ModelGrader",
    "PlannerJudge",
]
