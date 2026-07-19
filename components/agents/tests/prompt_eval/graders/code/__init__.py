"""Code-grader registry for the planner prompt eval.

Code graders are deterministic checks that never call an LLM. They
enforce structural invariants — JSON parses, every task has an
``agent_type`` field, the plan respects banned-word rules, and so on.
The LogSeq curriculum is explicit: pair every model grader with
code-grader floors so a flaky LLM-as-judge can't certify a
syntactically broken plan as great.

Each grader returns a :class:`CodeGradeResult` with a 0–10 score, a
list of reasons (one per failed assertion, empty when passing), and
a ``label`` so the report can group by category.

Adding a new code grader:

1. Create ``<grader_name>.py`` in this directory exposing a
   ``grade(plan, case) -> CodeGradeResult`` function.
2. Append it to ``DEFAULT_CODE_GRADERS`` below.
3. Add a test case to ``planner_v1.json`` (or the relevant dataset)
   that exercises the new grader's failure mode.

The aggregator (:func:`grade_with_code`) runs every grader in the
list and averages their scores. Pass a custom list to the evaluator
when an experiment needs a different mix.
"""
from __future__ import annotations

from typing import Any, Callable

from components.agents.domain.value_objects.plan_schemas import PlanSpec

from components.agents.tests.prompt_eval.graders.code._types import (
    AggregateCodeGrade,
    CodeGrader,
    CodeGradeResult,
)
from components.agents.tests.prompt_eval.graders.code.agent_type_routing import (
    grade as grade_agent_type_routing,
)
from components.agents.tests.prompt_eval.graders.code.banned_words import (
    BANNED_WORD_RULES,
    grade as grade_no_banned_words,
)
from components.agents.tests.prompt_eval.graders.code.json_validity import (
    grade as grade_json_validity,
)
from components.agents.tests.prompt_eval.graders.code.plan_shape import (
    grade as grade_plan_shape,
)


# Default registry — runs against every case unless the runner
# constructs its own list.
DEFAULT_CODE_GRADERS: tuple[CodeGrader, ...] = (
    grade_plan_shape,
    grade_agent_type_routing,
    grade_no_banned_words,
    grade_json_validity,
)


def grade_with_code(
    plan: PlanSpec | None,
    case: dict[str, Any],
    graders: tuple[CodeGrader, ...] = DEFAULT_CODE_GRADERS,
) -> AggregateCodeGrade:
    """Run every code grader and aggregate the scores.

    Returns an :class:`AggregateCodeGrade` whose ``overall_score`` is
    the unweighted mean of the sub-scores. The harness combines this
    with the model grader's score (also 0–10) by averaging — the
    Logseq curriculum's Lesson-5 pattern.
    """
    sub_scores = [grader(plan, case) for grader in graders]
    overall = sum(sub.score for sub in sub_scores) / max(len(sub_scores), 1)
    return AggregateCodeGrade(overall_score=overall, sub_scores=sub_scores)


__all__ = [
    "AggregateCodeGrade",
    "BANNED_WORD_RULES",
    "CodeGradeResult",
    "CodeGrader",
    "DEFAULT_CODE_GRADERS",
    "grade_agent_type_routing",
    "grade_json_validity",
    "grade_no_banned_words",
    "grade_plan_shape",
    "grade_with_code",
]
