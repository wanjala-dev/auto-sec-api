"""The rubric-verdict vocabulary — ONE definition, shared by writer and readers.

``RubricMiddleware`` grades a worker's answer and the result is folded into
``run_metadata["rubric_verdicts"][<task_id>]`` as a stamp whose ``verdict`` key
holds one of the strings below. That stamp then travels to at least four
readers: the deep-run stats projection, the posture fleet-health service, the
run-quality detector, and the finding card's ``run_telemetry``.

WHY THIS FILE EXISTS. It didn't, and the cost was total. The writer stamped
``{"verdict": "satisfied"}`` (``deep/rubric.py``); the deep-run stats reader
looked for a BOOLEAN under ``"satisfied"``, then ``"passed"``, found neither,
and counted every graded answer as a failure. ``rubric_pass_count`` on
``GET /ai/agents/runs/`` was therefore **0 for every run ever graded**, and
``rubric_fail_count`` equalled the verdict count regardless of what the grader
actually said — our only judge reported 100% failure and nothing looked wrong,
because a count of zero is a perfectly plausible number (ADR 0032 §1.3.2).

Two lessons are encoded here rather than written down somewhere:

1. **The verdict is a tri-state string, not a boolean.** ``max_iterations_reached``
   is not "failed" and is not "passed" — it is "the grader kept asking for
   revisions until the budget ran out". A boolean cannot carry that, which is
   why the boolean-shaped reader was the side that was wrong.
2. **A shared literal typed in four places is a shared literal that will drift
   in one of them.** Import from here.

Framework-free: stdlib only.
"""

from __future__ import annotations

#: The grader is satisfied — the ONLY passing verdict.
RUBRIC_VERDICT_SATISFIED = "satisfied"

#: The grader asked for a revision and the budget still allowed one.
RUBRIC_VERDICT_NEEDS_REVISION = "needs_revision"

#: The grader rejected the answer outright.
RUBRIC_VERDICT_FAILED = "failed"

#: The grader itself errored — not a judgement about the answer.
RUBRIC_VERDICT_GRADER_ERROR = "grader_error"

#: Derived, never emitted per-evaluation: a terminal ``needs_revision`` with the
#: iteration budget exhausted. Mirrors the middleware's private
#: ``_rubric_status``, which we cannot read from the graph output.
RUBRIC_VERDICT_MAX_ITERATIONS_REACHED = "max_iterations_reached"

#: Everything a single evaluation's ``result`` may be (the derived verdict
#: above is added by ``summarize_rubric_evaluations``).
RUBRIC_EVALUATION_RESULTS = frozenset(
    {
        RUBRIC_VERDICT_SATISFIED,
        RUBRIC_VERDICT_NEEDS_REVISION,
        RUBRIC_VERDICT_FAILED,
        RUBRIC_VERDICT_GRADER_ERROR,
    }
)

#: Verdicts that mean the answer did NOT pass and will not get another attempt.
#: ``needs_revision`` is deliberately absent: mid-loop it is not terminal.
RUBRIC_TERMINAL_FAIL_VERDICTS = frozenset(
    {
        RUBRIC_VERDICT_FAILED,
        RUBRIC_VERDICT_MAX_ITERATIONS_REACHED,
    }
)


def is_rubric_pass(verdict: str | None) -> bool:
    """True only for an EXPLICIT ``satisfied``.

    Fails closed on an unknown or missing verdict — but note that callers
    computing a pass RATE must not fold "missing" into the failure count.
    Absence of a grade is a third state (ADR 0032 D4); use
    :func:`is_rubric_graded` to build the denominator.
    """
    return str(verdict or "").strip() == RUBRIC_VERDICT_SATISFIED


def is_rubric_graded(verdict: str | None) -> bool:
    """Was this answer graded at all? The denominator test.

    An empty / absent verdict means the rubric never ran on it (middleware
    off, agent type not gradable, grader crashed before a result). Counting
    those as failures is how a judge that never ran reads as a judge that
    always fails.
    """
    return bool(str(verdict or "").strip())
