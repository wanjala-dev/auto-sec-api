"""Context Precision — fraction of retrieved chunks that are relevant.

RAGAS §3.1 defines Context Precision as the ratio of relevant chunks
to retrieved chunks, judged per chunk by an LLM. We follow the same
formula but adapt the prompt to our snapshot-section ground truth:
the LLM judges each chunk against the question + the expected answer
shape (so it's an answerable question, not just a "is this chunk
relevant" gut call).

For each retrieved chunk we ask: "does this chunk contribute material
that would help answer the question?" — yes/no. Score is yes / total.

Score = relevant_chunks / retrieved_chunks

Edge cases:
* No retrieved chunks → 0.0 (and an explanation in detail, so the
  report doesn't read like a passing run).
* Judge returns garbage for a chunk → that chunk counts as NOT
  relevant (conservative; better to under-count than over-count).

The judge call is per-chunk so a 5-chunk retrieval triggers 5 LLM
calls per prompt. The cache makes re-scoring nearly free, but the
first run is the dominant cost.

Reference: Es, S. et al. (2023) RAGAS §3.1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from tests.eval.rag.judge import Judge, JudgeRequest, build_cache_key
from tests.eval.rag.metrics import MetricResult


_SYSTEM_PROMPT = (
    "You are an evaluator deciding whether a retrieved chunk is relevant to "
    "answering the user's question. A chunk is relevant if its content would "
    "help a human compose a correct answer, even partially.\n"
    "\n"
    "Reply with EXACTLY this format, no prose before or after:\n"
    "VERDICT: <yes|no>\n"
    "REASON: <one short sentence>"
)


@dataclass
class ContextPrecision:
    name: str = "context_precision"
    judge_model: str = "gpt-4o-mini"
    judge_temperature: float = 0.0

    def score(
        self,
        *,
        prompt_id: str,
        question: str,
        retrieved_chunks: Sequence[dict],
        judge: Judge,
    ) -> MetricResult:
        if not retrieved_chunks:
            return MetricResult(
                name=self.name,
                score=0.0,
                detail={
                    "reason": "no retrieved chunks",
                    "verdicts": [],
                },
            )

        verdicts: list[dict] = []
        relevant_count = 0
        for idx, chunk in enumerate(retrieved_chunks):
            content = (chunk.get("content") or "").strip()
            if not content:
                verdicts.append(
                    {"chunk_idx": idx, "verdict": "no", "reason": "empty content"}
                )
                continue

            user = (
                f"Question: {question}\n\n"
                f"Retrieved chunk #{idx + 1}:\n{content}\n\n"
                "Is this chunk relevant to answering the question?"
            )
            request = JudgeRequest(
                prompt_id=f"{prompt_id}::chunk_{idx}",
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
            verdict, reason = _parse_verdict(response)
            verdicts.append(
                {
                    "chunk_idx": idx,
                    "verdict": verdict or "unparseable",
                    "reason": reason,
                    "section": (chunk.get("metadata") or {}).get("section", ""),
                }
            )
            if verdict == "yes":
                relevant_count += 1

        return MetricResult(
            name=self.name,
            score=relevant_count / len(retrieved_chunks),
            detail={
                "relevant_chunks": relevant_count,
                "total_chunks": len(retrieved_chunks),
                "verdicts": verdicts,
            },
        )


_VERDICT_RE = re.compile(r"VERDICT\s*:\s*(yes|no)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON\s*:\s*(.+)", re.IGNORECASE)


def _parse_verdict(text: str) -> tuple[str | None, str]:
    """Pull a yes/no verdict and reason out of the judge's reply.

    Returns (None, "") if the response can't be parsed — caller
    treats that as a non-relevant chunk (conservative).
    """
    if not text:
        return None, ""
    m = _VERDICT_RE.search(text)
    if not m:
        return None, ""
    reason_m = _REASON_RE.search(text)
    reason = reason_m.group(1).strip() if reason_m else ""
    return m.group(1).lower(), reason
