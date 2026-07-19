"""Answer Relevancy — LLM judges how directly the answer addresses the question.

RAGAS §3.2 measures Answer Relevancy by asking the LLM to generate
artificial questions from the answer, then comparing them to the
original question via cosine similarity in an embedding space. We
simplify to a direct 1-5 LLM rating because:

* Our eval set is small (30 prompts) — the embedding-based variant's
  variance reduction matters less.
* Direct rating is one LLM call instead of N+1 (one to generate
  questions, one per question to embed, one to compare).
* The simplified score correlates highly with the embedding variant in
  the RAGAS paper's own ablation (§5.3).

Score = (rating - 1) / 4, so a 5/5 maps to 1.0 and 1/5 maps to 0.0.

The judge prompt asks for a 1-5 rating + a one-line reason. Bad answers
(LLM returns text we can't parse as a 1-5 integer) score 0 and get
flagged in the detail field.

Reference: Es, S. et al. (2023) RAGAS §3.2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from tests.eval.rag.judge import Judge, JudgeRequest, build_cache_key
from tests.eval.rag.metrics import MetricResult

_SYSTEM_PROMPT = (
    "You are an evaluator scoring how directly an answer addresses the user's "
    "question. Rate on a 1-5 integer scale:\n"
    "  5 = answers the question directly and completely\n"
    "  4 = answers the question with minor omissions\n"
    "  3 = partially answers but with significant gaps\n"
    "  2 = touches on the topic but doesn't really answer\n"
    "  1 = does not address the question at all (off-topic, error, refusal)\n"
    "\n"
    "Reply with EXACTLY this format, no prose before or after:\n"
    "RATING: <int 1-5>\n"
    "REASON: <one short sentence>"
)


@dataclass
class AnswerRelevancy:
    name: str = "answer_relevancy"
    judge_model: str = "gpt-4o-mini"
    judge_temperature: float = 0.0

    def score(
        self,
        *,
        prompt_id: str,
        question: str,
        answer: str,
        judge: Judge,
    ) -> MetricResult:
        """Score answer relevancy via LLM rating.

        Empty / missing answers short-circuit to 0 — no LLM call.
        """
        if not answer or not answer.strip():
            return MetricResult(
                name=self.name,
                score=0.0,
                detail={"reason": "empty answer", "rating": 0},
            )

        user = (
            f"Question: {question}\n\n"
            f"Answer to evaluate:\n{answer.strip()}\n\n"
            "How well does the answer address the question?"
        )
        request = JudgeRequest(
            prompt_id=prompt_id,
            system=_SYSTEM_PROMPT,
            user=user,
            cache_key=build_cache_key(
                system=_SYSTEM_PROMPT,
                user=user,
                model=self.judge_model,
                temperature=self.judge_temperature,
            ),
        )
        response = judge.call(request)
        rating, reason = _parse_rating(response)
        if rating is None:
            return MetricResult(
                name=self.name,
                score=0.0,
                detail={
                    "rating": 0,
                    "reason": "unparseable judge response",
                    "raw_judge_response": response,
                },
            )
        return MetricResult(
            name=self.name,
            score=(rating - 1) / 4,
            detail={"rating": rating, "reason": reason},
        )


_RATING_RE = re.compile(r"RATING\s*:\s*(\d+)\b", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON\s*:\s*(.+)", re.IGNORECASE)


def _parse_rating(text: str) -> tuple[int | None, str]:
    """Pull a 1-5 integer rating and its reason out of the judge's reply.

    Tolerant of whitespace + casing variation but rejects ratings
    outside 1-5 — we'd rather a clear failure surface in the report
    than a silently clipped value.
    """
    if not text:
        return None, ""
    m = _RATING_RE.search(text)
    if not m:
        return None, ""
    rating = int(m.group(1))
    if not 1 <= rating <= 5:
        return None, ""
    reason_m = _REASON_RE.search(text)
    reason = reason_m.group(1).strip() if reason_m else ""
    return rating, reason
