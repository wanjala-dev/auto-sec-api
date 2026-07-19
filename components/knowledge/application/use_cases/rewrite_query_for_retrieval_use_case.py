"""Tier 3 #9 — LLM query rewriter for the workspace retrieval surface.

Vector search is weak at exact-match queries (proper nouns, recipient
names, donor emails) and at very short queries ("tldr") that lack
the semantic anchors a similarity search needs.  An LLM rewriter
turns ``"tldr"`` into something like ``"workspace mission summary
recipients donors active campaigns"`` — the embedding now lands closer
to the snapshot's identity / mission / activity chunks.

Two callers:

* ``deep_service._prefetch_retrieved_context`` (planner-side) — runs
  before every planner LLM call.
* ``BaseAgent._build_workspace_retrieval_tool`` (agent-side) — runs
  inside every ``retrieve_workspace_context`` tool invocation.

Cached per ``(workspace_id, raw_query)`` for ``TTL`` seconds so a chat
loop that re-asks the same short query doesn't pay the rewrite tax
twice.  TTL is short because we want any prompt edits to take effect
quickly.

Failure modes are silent: any LLM error returns the raw query
unchanged.  The retrieval pipeline keeps working — just without the
rewrite uplift on that one call.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #9.
"""
from __future__ import annotations

import logging
from typing import Optional

from components.knowledge.application.ports.key_value_cache_port import (
    KeyValueCachePort,
)

logger = logging.getLogger(__name__)

# Cache TTL — 1 hour.  Workspace identity / mission don't change
# faster than that, so a rewritten query is stable on the same scale.
# Versioned key so a future prompt change can flip the namespace.
CACHE_TTL_SECONDS = 3600
_CACHE_KEY_PREFIX = "knowledge:query_rewrite_v1"

# Default model — cheap, fast.  Callers can override per invocation.
# OpenAI's gpt-4o-mini is the cost/quality sweet spot for a 50-token
# rewriting prompt; Azure deployments substitute their own equivalent.
DEFAULT_REWRITER_MODEL = "gpt-4o-mini"

# The rewriter prompt — short, single-purpose.  Tells the LLM to
# expand without explaining: any preamble would land in the embedded
# query and degrade similarity.  See §12 hygiene rules.
_REWRITER_SYSTEM = (
    "You expand short or vague search queries into richer ones that "
    "improve semantic retrieval against a workspace knowledge base. "
    "The knowledge base contains workspace identity, mission, "
    "categories, operations, recent donations and recipients, top "
    "donors, active campaigns, open grants, and active projects.\n"
    "\n"
    "Rewrite the user's query into 5 to 12 keywords that surface "
    "those sections better. Keep proper nouns verbatim. Do not add "
    "preambles, explanations, or punctuation. Return the rewritten "
    "query and nothing else."
)


class RewriteQueryForRetrievalUseCase:
    """Rewrites a retrieval query via the configured LLM port.

    Construct once at boot (cheap); call ``rewrite()`` from every
    retrieval-bound code path.  The use case is provider-agnostic —
    it asks ``AILlmProvider`` for the default port and delegates the
    LLM call.
    """

    def __init__(
        self,
        *,
        cache_port: Optional[KeyValueCachePort] = None,
        model_name: str = DEFAULT_REWRITER_MODEL,
        max_input_chars: int = 240,
    ) -> None:
        # ``cache_port`` defaults to the Django adapter via the
        # provider — tests inject an in-memory fake to keep the
        # application layer framework-free.  ``model_name`` is
        # passed to the LLM adapter as the model parameter; the
        # default ``DEFAULT_REWRITER_MODEL`` is a Haiku/Mini tier
        # for cost.  ``max_input_chars`` guards against
        # pathologically long queries — anything over this is passed
        # through raw to skip the LLM call entirely.
        self._cache_port = cache_port
        self._model_name = model_name
        self._max_input_chars = max_input_chars

    def _cache(self) -> KeyValueCachePort:
        """Resolve the cache port lazily so the provider is imported
        only when the use case is actually used, not at import time.
        """
        if self._cache_port is not None:
            return self._cache_port
        from components.knowledge.application.providers.key_value_cache_provider import (
            key_value_cache,
        )

        self._cache_port = key_value_cache()
        return self._cache_port

    def rewrite(self, *, workspace_id: str, query: str) -> str:
        """Return a rewritten query, or the original on any failure.

        Empty / whitespace queries are returned unchanged (the
        retrieval surface already handles them).  Queries longer
        than ``max_input_chars`` are returned unchanged — they
        already carry enough signal to retrieve well.
        """
        raw = (query or "").strip()
        if not raw:
            return query
        if len(raw) > self._max_input_chars:
            return raw

        cache_port = self._cache()
        # Cache hit — return early.
        cache_key = self._cache_key(workspace_id, raw)
        cached = cache_port.get(cache_key)
        if cached:
            return cached

        rewritten = self._call_llm(raw)
        if not rewritten:
            return raw

        cache_port.set(cache_key, rewritten, ttl_seconds=CACHE_TTL_SECONDS)
        return rewritten

    def _call_llm(self, raw_query: str) -> Optional[str]:
        """One LLM call with full error swallowing.

        We return ``None`` on any failure so the caller falls back to
        the raw query.  Retrieval must never crash because a rewrite
        attempt did.
        """
        try:
            from components.knowledge.application.providers.ai_llm_provider import (
                AILlmProvider,
            )

            llm = AILlmProvider().get_default_port(model_name=self._model_name)
            response = llm.chat(
                messages=[
                    {"role": "system", "content": _REWRITER_SYSTEM},
                    {"role": "user", "content": raw_query},
                ],
                temperature=0.0,
                max_tokens=64,
            )
            rewritten = (response.content or "").strip()
            if not rewritten:
                return None
            # Defensive cleanup — strip surrounding quotes that some
            # models occasionally add even when told not to.
            rewritten = rewritten.strip(" \"'")
            return rewritten or None
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "knowledge: query rewriter LLM call failed, falling "
                "back to raw query",
                exc_info=True,
            )
            return None

    @staticmethod
    def _cache_key(workspace_id: str, raw_query: str) -> str:
        # Length cap on the query portion keeps the cache key from
        # ballooning.  We already pass-through queries longer than
        # ``max_input_chars`` so the cap here is just defensive.
        safe_q = raw_query[:240]
        return f"{_CACHE_KEY_PREFIX}:{workspace_id}:{safe_q}"
