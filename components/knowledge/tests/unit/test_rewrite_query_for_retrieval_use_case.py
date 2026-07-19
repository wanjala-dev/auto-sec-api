"""Tier 3 #9 — unit tests for the query rewriter use case.

The LLM port is stubbed; we verify the contract:

* Empty / whitespace queries pass through.
* Long queries (over ``max_input_chars``) pass through.
* LLM returns the rewritten query and the use case caches it.
* Second call for the same (workspace_id, query) hits the cache
  (no second LLM call).
* LLM errors fall back to the raw query.
* Empty / quoted-only LLM responses fall back to the raw query.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #9.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from components.knowledge.application.ports.llm_port import LlmResponse
from components.knowledge.application.use_cases.rewrite_query_for_retrieval_use_case import (
    CACHE_TTL_SECONDS,
    DEFAULT_REWRITER_MODEL,
    RewriteQueryForRetrievalUseCase,
)


@pytest.fixture(autouse=True)
def _flush_cache_between_tests():
    cache.clear()
    yield
    cache.clear()


def _stub_llm(response_content: str):
    """Return a patcher for AILlmProvider.get_default_port that yields
    a fake LlmPort returning ``response_content`` from chat()."""
    fake = MagicMock()
    fake.chat.return_value = LlmResponse(content=response_content)
    return patch(
        "components.knowledge.application.providers."
        "ai_llm_provider.AILlmProvider.get_default_port",
        return_value=fake,
    ), fake


class TestPassThroughCases:
    def test_empty_query_returns_unchanged(self):
        use_case = RewriteQueryForRetrievalUseCase()
        assert use_case.rewrite(workspace_id="ws-1", query="") == ""
        assert use_case.rewrite(workspace_id="ws-1", query="   ") == "   "

    def test_long_query_passes_through_without_llm_call(self):
        use_case = RewriteQueryForRetrievalUseCase(max_input_chars=20)
        long_query = "a" * 50

        patcher, fake = _stub_llm("rewritten")
        with patcher:
            result = use_case.rewrite(workspace_id="ws-1", query=long_query)

        assert result == long_query
        fake.chat.assert_not_called()


class TestRewriteHappyPath:
    def test_returns_rewritten_query_on_llm_success(self):
        use_case = RewriteQueryForRetrievalUseCase()
        patcher, fake = _stub_llm(
            "workspace mission summary recipients donors active campaigns"
        )
        with patcher:
            result = use_case.rewrite(workspace_id="ws-1", query="tldr")

        assert result == (
            "workspace mission summary recipients donors active campaigns"
        )
        fake.chat.assert_called_once()
        # Verify the system prompt + user message shape.
        call_messages = fake.chat.call_args.kwargs["messages"]
        assert call_messages[0]["role"] == "system"
        assert call_messages[1] == {"role": "user", "content": "tldr"}

    def test_uses_configured_model_name(self):
        use_case = RewriteQueryForRetrievalUseCase(model_name="gpt-4o-mini")
        patcher, fake = _stub_llm("expanded")
        with patch(
            "components.knowledge.application.providers."
            "ai_llm_provider.AILlmProvider.get_default_port",
            return_value=fake.chat.return_value
            and MagicMock(chat=fake.chat),
        ) as mock_get:
            use_case.rewrite(workspace_id="ws-1", query="tldr")

        # The provider was asked for the configured model.
        assert mock_get.call_args.kwargs == {"model_name": "gpt-4o-mini"}

    def test_default_model_is_haiku_class(self):
        # Cost guardrail — we should default to a cheap fast model,
        # not GPT-4 / Sonnet / Opus.  Renames are fine; what we lock
        # is "not the expensive tier".
        assert "mini" in DEFAULT_REWRITER_MODEL.lower() or (
            "haiku" in DEFAULT_REWRITER_MODEL.lower()
        )

    def test_strips_surrounding_quotes_some_models_add(self):
        use_case = RewriteQueryForRetrievalUseCase()
        patcher, _ = _stub_llm('"workspace mission summary"')
        with patcher:
            result = use_case.rewrite(workspace_id="ws-1", query="tldr")
        assert result == "workspace mission summary"


class TestCaching:
    def test_second_call_for_same_query_skips_llm(self):
        use_case = RewriteQueryForRetrievalUseCase()
        patcher, fake = _stub_llm("rewritten once")
        with patcher:
            first = use_case.rewrite(workspace_id="ws-1", query="tldr")
            second = use_case.rewrite(workspace_id="ws-1", query="tldr")

        assert first == "rewritten once"
        assert second == "rewritten once"
        # LLM called exactly once across both invocations.
        assert fake.chat.call_count == 1

    def test_different_workspaces_get_separate_cache_keys(self):
        use_case = RewriteQueryForRetrievalUseCase()
        patcher, fake = _stub_llm("a")
        with patcher:
            use_case.rewrite(workspace_id="ws-A", query="tldr")
            use_case.rewrite(workspace_id="ws-B", query="tldr")

        # Two separate cache keys → two LLM calls.
        assert fake.chat.call_count == 2


class TestErrorFallback:
    def test_llm_error_falls_back_to_raw_query(self):
        use_case = RewriteQueryForRetrievalUseCase()
        fake = MagicMock()
        fake.chat.side_effect = RuntimeError("openai down")
        with patch(
            "components.knowledge.application.providers."
            "ai_llm_provider.AILlmProvider.get_default_port",
            return_value=fake,
        ):
            result = use_case.rewrite(workspace_id="ws-1", query="tldr")

        assert result == "tldr"

    def test_empty_llm_response_falls_back_to_raw_query(self):
        use_case = RewriteQueryForRetrievalUseCase()
        patcher, _ = _stub_llm("   ")
        with patcher:
            result = use_case.rewrite(workspace_id="ws-1", query="tldr")
        assert result == "tldr"

    def test_quoted_empty_llm_response_falls_back_to_raw_query(self):
        use_case = RewriteQueryForRetrievalUseCase()
        patcher, _ = _stub_llm('""')
        with patcher:
            result = use_case.rewrite(workspace_id="ws-1", query="tldr")
        assert result == "tldr"

    def test_provider_construction_failure_falls_back(self):
        """Even AILlmProvider() raising must not break retrieval."""
        use_case = RewriteQueryForRetrievalUseCase()
        with patch(
            "components.knowledge.application.providers."
            "ai_llm_provider.AILlmProvider.__init__",
            side_effect=RuntimeError("provider boot failed"),
        ):
            result = use_case.rewrite(workspace_id="ws-1", query="tldr")
        assert result == "tldr"


class TestCacheTtlContract:
    def test_cache_ttl_is_hours_scale(self):
        # 1 hour is the design value — captures rewriter prompt edits
        # within a deploy cycle without paying LLM tax for the common
        # repeated short query.
        assert CACHE_TTL_SECONDS == 3600
