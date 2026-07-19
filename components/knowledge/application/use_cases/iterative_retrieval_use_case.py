"""Tier 3 #12 — agentic retrieval with self-verification + retry.

Basic RAG fires one search and trusts whatever comes back.  Agentic
RAG (per the 2026 audit research, arxiv 2501.09136) wraps a reasoning
loop around retrieval: after the initial search, the agent evaluates
*"are these chunks sufficient to answer the goal?"*.  If not, it
reformulates the query — using the unhelpful chunks as negative
context — and searches again.  Bounded by a max round count to avoid
token blow-up.

This use case is **opt-in** via the ``KNOWLEDGE_SELF_VERIFY_ENABLED``
env var, default ``false``.  Three LLM round-trips per planner call
is real cost; we expose the capability but only enable it where the
quality lift is worth paying for.

Wired into ``_prefetch_retrieved_context`` (planner-side, high
leverage, low frequency).  Not wired into the per-agent retrieval
tool (low leverage, high frequency — every agent calls it).

Failure modes are silent: any LLM failure ends the loop and returns
the best round's chunks.  Self-verification must never crash
retrieval.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #12.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Protocol

from components.knowledge.application.ports.vector_store_port import RetrievedChunk

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 3
SUFFICIENCY_THRESHOLD = 7  # 1-10 scale; ≥7 stops the loop
DEFAULT_VERIFIER_MODEL = "gpt-4o-mini"


def is_self_verify_enabled() -> bool:
    """Read the opt-in env var.  Default off — three LLM round-trips
    per planner call is real cost.
    """
    return os.environ.get("KNOWLEDGE_SELF_VERIFY_ENABLED", "").lower() in {
        "true", "1", "yes",
    }


class _RetrieverProtocol(Protocol):
    """Minimal interface we require from the injected retriever — lets
    callers wire the rewriter / reranker pipeline once and reuse it
    across rounds without this module knowing about either."""

    def __call__(
        self, *, workspace_id: str, query: str
    ) -> List[RetrievedChunk]:
        ...


@dataclass(frozen=True)
class _Round:
    query: str
    chunks: List[RetrievedChunk]
    sufficiency: int  # 1-10; 0 if scoring failed (treated as insufficient)


_VERIFIER_SYSTEM = (
    "You score how well a set of retrieved knowledge-base chunks "
    "answers a user query.\n"
    "\n"
    "Return a single integer 1-10 and nothing else:\n"
    "  10 — the chunks fully answer the query.\n"
    "  7-9 — the chunks substantially answer the query.\n"
    "  4-6 — partial answer; key details missing.\n"
    "  1-3 — the chunks don't address the query at all.\n"
)

_REWRITER_RETRY_SYSTEM = (
    "You rewrite a search query that failed to surface useful chunks.\n"
    "\n"
    "Given the original user goal and the unhelpful chunks the previous "
    "query returned, write a new search query that surfaces *different* "
    "content from the knowledge base. Avoid repeating terms that "
    "dominate the unhelpful chunks. Keep proper nouns verbatim.\n"
    "\n"
    "Return only the new query, no preamble, no punctuation."
)


class IterativeRetrievalUseCase:
    """Retrieve → verify → reformulate → retry, up to ``max_rounds``."""

    def __init__(
        self,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        model_name: str = DEFAULT_VERIFIER_MODEL,
    ) -> None:
        self._max_rounds = max(1, max_rounds)
        self._model_name = model_name

    def retrieve(
        self,
        *,
        workspace_id: str,
        goal: str,
        retriever: _RetrieverProtocol,
    ) -> List[RetrievedChunk]:
        """Run the iterative loop, return the best round's chunks.

        Round 1 always runs with the original goal.  If sufficiency
        clears the threshold, we return immediately.  Otherwise,
        rounds 2..max_rounds reformulate using the previous round's
        unhelpful chunks as negative context.

        If every round falls below the threshold, we return the
        round with the highest sufficiency score (still useful — the
        LLM gets *something* to ground against).
        """
        rounds: List[_Round] = []
        current_query = goal

        for round_num in range(1, self._max_rounds + 1):
            chunks = self._safe_retrieve(
                retriever=retriever,
                workspace_id=workspace_id,
                query=current_query,
            )
            sufficiency = self._score_sufficiency(goal=goal, chunks=chunks)
            rounds.append(
                _Round(
                    query=current_query, chunks=chunks, sufficiency=sufficiency
                )
            )

            if sufficiency >= SUFFICIENCY_THRESHOLD:
                logger.info(
                    "knowledge: iterative retrieval cleared threshold "
                    "round=%s sufficiency=%s workspace_id=%s",
                    round_num,
                    sufficiency,
                    workspace_id,
                )
                return chunks

            if round_num == self._max_rounds:
                break

            next_query = self._reformulate(
                original_goal=goal,
                failed_query=current_query,
                failed_chunks=chunks,
            )
            if not next_query or next_query == current_query:
                logger.debug(
                    "knowledge: reformulator returned same / empty "
                    "query, stopping loop"
                )
                break
            current_query = next_query

        best = max(rounds, key=lambda r: r.sufficiency)
        logger.info(
            "knowledge: iterative retrieval exhausted rounds workspace_id=%s "
            "best_sufficiency=%s rounds=%s",
            workspace_id,
            best.sufficiency,
            len(rounds),
        )
        return best.chunks

    def _safe_retrieve(
        self,
        *,
        retriever: _RetrieverProtocol,
        workspace_id: str,
        query: str,
    ) -> List[RetrievedChunk]:
        try:
            return retriever(workspace_id=workspace_id, query=query)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "knowledge: iterative retriever inner search failed, "
                "treating round as empty",
                exc_info=True,
            )
            return []

    def _score_sufficiency(
        self, *, goal: str, chunks: List[RetrievedChunk]
    ) -> int:
        if not chunks:
            return 0
        try:
            from components.knowledge.application.providers.ai_llm_provider import (
                AILlmProvider,
            )

            llm = AILlmProvider().get_default_port(model_name=self._model_name)
            joined = "\n\n".join(
                f"[chunk {i}] {c.content}" for i, c in enumerate(chunks, 1)
            )
            user_message = (
                f"Query:\n{goal}\n\nRetrieved chunks:\n{joined}\n\n"
                "Score 1-10:"
            )
            response = llm.chat(
                messages=[
                    {"role": "system", "content": _VERIFIER_SYSTEM},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_tokens=4,
            )
            text = (response.content or "").strip()
            return _parse_sufficiency_score(text)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "knowledge: sufficiency scorer failed, treating as "
                "insufficient",
                exc_info=True,
            )
            return 0

    def _reformulate(
        self,
        *,
        original_goal: str,
        failed_query: str,
        failed_chunks: List[RetrievedChunk],
    ) -> Optional[str]:
        try:
            from components.knowledge.application.providers.ai_llm_provider import (
                AILlmProvider,
            )

            llm = AILlmProvider().get_default_port(model_name=self._model_name)
            # Truncate failed-chunk content so a long unhelpful response
            # doesn't dominate the rewriter's input window.
            joined = "\n\n".join(
                f"[unhelpful {i}] {(c.content or '')[:200]}"
                for i, c in enumerate(failed_chunks[:5], 1)
            )
            user_message = (
                f"Original user goal:\n{original_goal}\n\n"
                f"Failed search query:\n{failed_query}\n\n"
                f"Unhelpful chunks returned:\n{joined}\n\n"
                "New search query (one line):"
            )
            response = llm.chat(
                messages=[
                    {"role": "system", "content": _REWRITER_RETRY_SYSTEM},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,
                max_tokens=64,
            )
            text = (response.content or "").strip().strip(" \"'")
            return text or None
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "knowledge: retry-rewriter failed, stopping loop",
                exc_info=True,
            )
            return None


def _parse_sufficiency_score(text: str) -> int:
    """Defensive parse: pull the first integer 1-10 from the response.

    Some models occasionally add a period, a word, or surrounding
    whitespace despite the "single integer" instruction.  Returning
    0 for any unparseable response treats it as insufficient — safer
    than a false-positive that stops the loop early.
    """
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    if not digits:
        return 0
    try:
        value = int(digits)
    except ValueError:
        return 0
    return max(0, min(10, value))
