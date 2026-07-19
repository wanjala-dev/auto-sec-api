"""Deterministic writing-quality code graders (no LLM).

Each grades the generated draft dict against the case fixture and returns
a ``CodeGradeResult`` (0–10 + reasons). The aggregator averages them into
an ``AggregateCodeGrade`` — the same shape the planner eval uses, so the
harness + report browser render both families identically.

The draft dict shape (from ``GenerateInteractiveDraftUseCase.execute``):
    {title, body_html, excerpt, sections, source_chunks, faithfulness, ...}

The case fixture carries the ground truth under ``context``:
    {retrieved_context: [fact strings], voice: {banned_terms, ...},
     kind, recipient_name, ...}
"""

from __future__ import annotations

import re
from typing import Any

from components.agents.domain.services.faithfulness_verifier import (
    FaithfulnessVerifier,
)
from components.agents.domain.services.readability import score_readability
from components.agents.tests.prompt_eval.graders.code._types import (
    AggregateCodeGrade,
    CodeGradeResult,
)

_WORD_BOUNDARY = "(?<![A-Za-z]){term}(?![A-Za-z])"
_verifier = FaithfulnessVerifier()


def _body_html(artifact: Any) -> str:
    if not isinstance(artifact, dict):
        return ""
    return str(artifact.get("body_html") or "")


def _grounding_facts(case: dict[str, Any]) -> list[str]:
    context = case.get("context") or {}
    facts = context.get("retrieved_context") or []
    return [str(f) for f in facts if f]


def grade_faithfulness(artifact: Any, case: dict[str, Any]) -> CodeGradeResult:
    """Every figure in the copy must be grounded in the case's facts.

    Reuses the SEE-171 verifier — money/counts/dates are strict, names
    advisory. An ungrounded figure is the worst writing failure (it's how
    a thank-you letter ends up citing a donation that never happened).
    """
    body = _body_html(artifact)
    if not body.strip():
        return CodeGradeResult(
            label="faithfulness", score=0, reasons=["empty draft — nothing generated"]
        )
    report = _verifier.verify(
        generated_html=body, grounding_texts=_grounding_facts(case)
    )
    if report.ok:
        return CodeGradeResult(label="faithfulness", score=10)
    reasons = [
        f"ungrounded figure: {fig}" for fig in report.unsupported_numbers
    ]
    score = max(0, 10 - 3 * len(report.unsupported_numbers))
    return CodeGradeResult(label="faithfulness", score=score, reasons=reasons)


def grade_voice(artifact: Any, case: dict[str, Any]) -> CodeGradeResult:
    """No workspace-banned terminology in the copy.

    The case fixture's ``voice.banned_terms`` lists words the workspace
    has ruled out (e.g. "child"/"kid" when the rule is to say "recipient").
    A whole-word, case-insensitive match flags a violation.
    """
    context = case.get("context") or {}
    voice = context.get("voice") or {}
    banned = [str(t).strip() for t in (voice.get("banned_terms") or []) if str(t).strip()]
    if not banned:
        # No voice rules to enforce for this case — neutral pass.
        return CodeGradeResult(label="voice", score=10)

    text = _body_html(artifact).lower()
    reasons: list[str] = []
    for term in banned:
        pattern = _WORD_BOUNDARY.format(term=re.escape(term.lower()))
        if re.search(pattern, text):
            reasons.append(f"uses banned term '{term}' (workspace voice rule)")
    score = 10 if not reasons else max(0, 10 - 3 * len(reasons))
    return CodeGradeResult(label="voice", score=score, reasons=reasons)


def grade_readability(artifact: Any, case: dict[str, Any]) -> CodeGradeResult:  # noqa: ARG001
    """Copy should read at plain-English level (Flesch Reading Ease ≳ 50)."""
    body = _body_html(artifact)
    if not body.strip():
        return CodeGradeResult(
            label="readability", score=0, reasons=["empty draft — nothing to read"]
        )
    result = score_readability(body)
    ease = result.flesch_reading_ease
    # Band the continuous score into a 0–10 grade. 60+ is plain English;
    # below 30 is dense/academic and hard for a general donor audience.
    if ease >= 60:
        score = 10
    elif ease >= 50:
        score = 8
    elif ease >= 40:
        score = 6
    elif ease >= 30:
        score = 4
    else:
        score = 2
    reasons = (
        []
        if score >= 8
        else [
            f"Flesch reading ease {ease:.0f} "
            f"(grade {result.flesch_kincaid_grade:.0f}); aim for ≥50"
        ]
    )
    return CodeGradeResult(label="readability", score=score, reasons=reasons)


def grade_structure(artifact: Any, case: dict[str, Any]) -> CodeGradeResult:
    """Draft must have a title + non-trivial body; newsletters need sections."""
    if not isinstance(artifact, dict):
        return CodeGradeResult(
            label="structure", score=0, reasons=["no draft artifact returned"]
        )
    body = str(artifact.get("body_html") or "")
    title = str(artifact.get("title") or "")
    # An empty body is a structural void — no draft at all. Hard zero,
    # consistent with the faithfulness + readability graders.
    if not body.strip():
        return CodeGradeResult(
            label="structure", score=0, reasons=["body_html is empty"]
        )

    reasons: list[str] = []
    if len(re.sub(r"<[^>]+>", "", body).split()) < 20:
        reasons.append("body is too short to be a real draft (<20 words)")
    if not title.strip():
        reasons.append("missing title")

    kind = str((case.get("context") or {}).get("kind") or case.get("kind") or "")
    if kind == "newsletter":
        sections = artifact.get("sections") or []
        if not sections:
            reasons.append("newsletter has no sections")

    score = 10 if not reasons else max(0, 10 - 4 * len(reasons))
    return CodeGradeResult(label="structure", score=score, reasons=reasons)


DEFAULT_WRITING_CODE_GRADERS = (
    grade_faithfulness,
    grade_voice,
    grade_readability,
    grade_structure,
)


def grade_writing_with_code(
    artifact: Any,
    case: dict[str, Any],
    graders: tuple = DEFAULT_WRITING_CODE_GRADERS,
) -> AggregateCodeGrade:
    """Run every writing code grader and average the scores."""
    sub_scores = [grader(artifact, case) for grader in graders]
    overall = sum(sub.score for sub in sub_scores) / max(len(sub_scores), 1)
    return AggregateCodeGrade(overall_score=overall, sub_scores=sub_scores)
