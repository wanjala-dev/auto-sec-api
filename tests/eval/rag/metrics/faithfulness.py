"""Faithfulness — fraction of answer claims supported by retrieved context.

RAGAS §3.4 measures Faithfulness in two LLM passes:

1. **Extract** atomic factual claims from the answer text.
2. **Judge** each claim: is it supported by the retrieved context?

Score = supported_claims / total_claims.

Faithfulness is the "is the model hallucinating?" metric. A high
Faithfulness with low Answer Relevancy means the model is being
truthful but missing the point. A high Faithfulness with high Answer
Relevancy is the target. A low Faithfulness — claims unsupported by
retrieved context — is the failure mode RAG is supposed to prevent.

Edge cases:
* Empty answer → 0.0 (no claims, but treat as failure rather than
  vacuously perfect so the report flags it).
* No claims extracted (the LLM returns nothing parseable) → 0.0 with
  a clear reason in the detail.
* All claims found unsupported → 0.0.

The metric is the most expensive of the four: it triggers two LLM
calls plus N judge calls per prompt (where N is the number of
claims). The cache makes re-scoring cheap.

Reference: Es, S. et al. (2023) RAGAS §3.4.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from tests.eval.rag.judge import Judge, JudgeRequest, build_cache_key
from tests.eval.rag.metrics import MetricResult


_EXTRACT_SYSTEM = (
    "You extract atomic factual claims from a piece of text. A claim is a "
    "single declarative sentence stating one fact. Break compound sentences "
    "into separate claims. Skip filler, hedging, and questions.\n"
    "\n"
    "Reply with EXACTLY this format, no prose before or after:\n"
    "CLAIM 1: <sentence>\n"
    "CLAIM 2: <sentence>\n"
    "... and so on. If the text has no factual claims, reply NO_CLAIMS."
)

_JUDGE_SYSTEM = (
    "You decide whether a claim is supported by a body of context. A claim "
    "is supported if the context contains material that asserts the same "
    "thing or directly implies it. Hedged context (\"may\", \"might\") does "
    "not support a definite claim.\n"
    "\n"
    "Reply with EXACTLY this format, no prose before or after:\n"
    "VERDICT: <supported|unsupported>\n"
    "REASON: <one short sentence>"
)


@dataclass
class Faithfulness:
    name: str = "faithfulness"
    judge_model: str = "gpt-4o-mini"
    judge_temperature: float = 0.0

    def score(
        self,
        *,
        prompt_id: str,
        answer: str,
        retrieved_chunks: Sequence[dict],
        judge: Judge,
        tool_evidence: Sequence[dict] = (),
    ) -> MetricResult:
        if not answer or not answer.strip():
            return MetricResult(
                name=self.name,
                score=0.0,
                detail={"reason": "empty answer", "claims": []},
            )

        # Phase 1 — extract atomic claims from the answer.
        extract_user = (
            f"Text to extract claims from:\n{answer.strip()}\n\n"
            "List atomic claims."
        )
        extract_request = JudgeRequest(
            prompt_id=f"{prompt_id}::extract",
            system=_EXTRACT_SYSTEM,
            user=extract_user,
            cache_key=build_cache_key(
                system=_EXTRACT_SYSTEM,
                user=extract_user,
                model=self.judge_model,
                temperature=self.judge_temperature,
            ),
        )
        claims = _parse_claims(judge.call(extract_request))
        if not claims:
            return MetricResult(
                name=self.name,
                score=0.0,
                detail={
                    "reason": "no parseable claims extracted",
                    "claims": [],
                },
            )

        # Phase 2 — judge each claim against the context. Tool
        # observations (donation_agent ORM reads, financial_agent
        # aggregates) are rendered as authoritative blocks alongside
        # retrieved chunks so the judge treats them as ground truth
        # the chat path actually saw, not as a second retrieved
        # corpus to be skeptical of. Without this the transactional
        # category sits near 0 because every dollar-amount claim
        # looks unsupported when the snapshot chunks don't carry
        # transaction rows.
        context_text = _format_context(retrieved_chunks, tool_evidence)
        if not context_text:
            # No retrieved chunks AND no tool evidence — every claim
            # is unsupported by definition. Don't waste judge calls.
            return MetricResult(
                name=self.name,
                score=0.0,
                detail={
                    "reason": "no retrieved context or tool evidence to support claims",
                    "claims": [{"claim": c, "verdict": "unsupported"} for c in claims],
                },
            )

        verdicts: list[dict] = []
        supported_count = 0
        for idx, claim in enumerate(claims):
            user = (
                f"Context:\n{context_text}\n\n"
                f"Claim: {claim}\n\n"
                "Is the claim supported by the context?"
            )
            request = JudgeRequest(
                prompt_id=f"{prompt_id}::claim_{idx}",
                system=_JUDGE_SYSTEM,
                user=user,
                cache_key=build_cache_key(
                    system=_JUDGE_SYSTEM,
                    user=user,
                    model=self.judge_model,
                    temperature=self.judge_temperature,
                ),
            )
            verdict, reason = _parse_verdict(judge.call(request))
            verdicts.append(
                {
                    "claim": claim,
                    "verdict": verdict or "unparseable",
                    "reason": reason,
                }
            )
            if verdict == "supported":
                supported_count += 1

        return MetricResult(
            name=self.name,
            score=supported_count / len(claims),
            detail={
                "supported_claims": supported_count,
                "total_claims": len(claims),
                "claims": verdicts,
            },
        )


_CLAIM_RE = re.compile(r"^\s*CLAIM\s+\d+\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_VERDICT_RE = re.compile(r"VERDICT\s*:\s*(supported|unsupported)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON\s*:\s*(.+)", re.IGNORECASE)


def _parse_claims(text: str) -> list[str]:
    """Parse `CLAIM N: ...` lines into a list of stripped claim strings.

    Returns empty list if the text is `NO_CLAIMS` or contains no
    parseable claim lines.
    """
    if not text or "NO_CLAIMS" in text.upper():
        return []
    return [m.group(1).strip() for m in _CLAIM_RE.finditer(text)]


def _parse_verdict(text: str) -> tuple[str | None, str]:
    """Pull a supported/unsupported verdict out of the judge's reply."""
    if not text:
        return None, ""
    m = _VERDICT_RE.search(text)
    if not m:
        return None, ""
    reason_m = _REASON_RE.search(text)
    reason = reason_m.group(1).strip() if reason_m else ""
    return m.group(1).lower(), reason


def _format_context(
    chunks: Sequence[dict],
    tool_evidence: Sequence[dict] = (),
) -> str:
    """Render retrieved chunks + tool observations as a context block.

    Tool observations are emitted FIRST and tagged as ``[tool …]``
    blocks so the judge reads them as authoritative material the
    agent actually executed (an ORM query result, an arithmetic
    sum, a reranked search hit). Chunks come after, tagged
    ``[chunk N section=…]`` as before.

    Order matters: the judge gives equal credence to whatever's in
    the context, but humans reading the verdict detail get a
    cleaner story when the tool evidence — the data the agent
    actively pulled to answer — appears before the retrieved
    snapshot it had ambiently. The cache key is content-derived,
    so reordering invalidates cached judgments only when the
    underlying data changes.

    Empty chunks / observations are skipped so a tool that
    returned ``""`` doesn't show up as a dangling header.
    """
    lines: list[str] = []
    for idx, observation in enumerate(tool_evidence):
        output = (observation.get("tool_output") or "").strip()
        if not output:
            continue
        tool_name = (observation.get("tool_name") or "").strip()
        agent_type = (observation.get("agent_type") or "").strip()
        header_bits = [f"tool {idx + 1}"]
        if agent_type:
            header_bits.append(f"agent={agent_type}")
        if tool_name:
            header_bits.append(f"name={tool_name}")
        truncated = observation.get("truncated_output")
        if truncated:
            header_bits.append("truncated")
        lines.append("[" + " ".join(header_bits) + "]")
        lines.append(output)
        lines.append("")
    for idx, chunk in enumerate(chunks):
        content = (chunk.get("content") or "").strip()
        if not content:
            continue
        section = (chunk.get("metadata") or {}).get("section", "")
        header = f"[chunk {idx + 1}"
        if section:
            header += f" section={section}"
        header += "]"
        lines.append(header)
        lines.append(content)
        lines.append("")
    return "\n".join(lines).strip()
