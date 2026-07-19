"""Anthropic Chat Model factory shim for :class:`LLMFactory`.

Mirrors the ``chatopenai`` / ``azure`` shape so
``LLMFactory.create_llm(provider='anthropic', model_name=...)``
returns a langchain ``ChatAnthropic`` instance the rest of the
pipeline can call exactly like the OpenAI / Azure equivalents.

Why this exists (Wave 4 of the prompt-evaluation plan): the LLM-as-
judge in ``PlannerJudge`` resolves its backend via
``LLMFactory.get_llm`` so we can swap judges without editing the
grader. Adding Anthropic here unlocks the cross-vendor debiasing
check the Logseq curriculum calls out as the single most effective
debiasing move (OpenAI-as-judge vs Claude-as-judge for the same
dataset).

The bigger ``AnthropicLlmAdapter`` at
``components/knowledge/infrastructure/adapters/llm/anthropic_llm_adapter.py``
wraps a ChatAnthropic with the ``LlmPort`` contract used by the
production deep-agent pipeline. The grader pipeline doesn't go
through that adapter — it uses langchain's `.invoke(messages)` API
directly — so this lightweight shim is enough.
"""
from __future__ import annotations

import os
from typing import Any

try:
    from langchain_anthropic import ChatAnthropic  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — keeps the factory importable on hosts without the package
    ChatAnthropic = None  # type: ignore[assignment]


def build_llm(
    chat_args: Any = None,
    model_name: str = "claude-sonnet-4-20250514",
    **kwargs: Any,
):
    """Build a ChatAnthropic instance with the factory's standard config knobs.

    Honours the same environment variables as the production adapter:

    * ``ANTHROPIC_API_KEY`` — required at runtime.
    * ``ANTHROPIC_REQUEST_TIMEOUT`` / ``ANTHROPIC_MAX_RETRIES`` —
      optional tuning, fall back to library defaults when unset.
    """
    if ChatAnthropic is None:
        raise RuntimeError(
            "langchain-anthropic is not installed. Add it to "
            "requirements/base.txt before using provider='anthropic'."
        )

    config: dict[str, Any] = {
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "model": model_name,
        "temperature": kwargs.pop("temperature", 0.0),
        "max_tokens": kwargs.pop("max_tokens", 1024),
        "streaming": kwargs.pop("streaming", False),
    }

    timeout_env = os.environ.get("ANTHROPIC_REQUEST_TIMEOUT")
    if timeout_env:
        try:
            config["timeout"] = float(timeout_env)
        except ValueError:
            pass

    retries_env = os.environ.get("ANTHROPIC_MAX_RETRIES")
    if retries_env:
        try:
            config["max_retries"] = int(retries_env)
        except ValueError:
            pass

    config.update(kwargs)
    return ChatAnthropic(**config)


def build_streaming_llm(chat_args: Any = None, model_name: str = "claude-sonnet-4-20250514", **kwargs: Any):
    """Streaming variant — same signature, ``streaming=True``."""
    kwargs.setdefault("streaming", True)
    return build_llm(chat_args=chat_args, model_name=model_name, **kwargs)
