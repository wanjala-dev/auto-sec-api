"""Anthropic Claude LLM adapter — wraps langchain_anthropic.ChatAnthropic behind LlmPort.

Supports Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku, and future
Claude models.  Reads ``ANTHROPIC_API_KEY`` from the environment.

Usage via the dynamic registry::

    llm = AIProvider.llm().get_port("anthropic", model_name="claude-sonnet-4-20250514")
    result = llm.invoke("Summarize this workspace data ...")
"""

from __future__ import annotations

import os
from typing import Iterator

from components.knowledge.application.ports.llm_port import LlmPort, LlmResponse


class AnthropicLlmAdapter(LlmPort):
    """Adapter for Anthropic Claude models via LangChain."""

    def __init__(
        self,
        *,
        model_name: str = "claude-sonnet-4-20250514",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> None:
        self._model_name = model_name
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._llm = None
        self._streaming_llm = None

    def _build_llm(self, streaming: bool = False):
        """Lazy-construct the ChatAnthropic instance."""
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-untyped]

        return ChatAnthropic(
            model=self._model_name,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            streaming=streaming,
        )

    def _get_llm(self):
        if self._llm is None:
            self._llm = self._build_llm(streaming=False)
        return self._llm

    def _get_streaming_llm(self):
        if self._streaming_llm is None:
            self._streaming_llm = self._build_llm(streaming=True)
        return self._streaming_llm

    def chat(self, messages: list[dict[str, str]], **kwargs) -> LlmResponse:
        from langchain.schema import HumanMessage, SystemMessage, AIMessage

        role_map = {"system": SystemMessage, "user": HumanMessage, "human": HumanMessage, "assistant": AIMessage, "ai": AIMessage}
        lc_messages = [role_map.get(m.get("role", "user"), HumanMessage)(content=m.get("content", "")) for m in messages]

        llm = self._get_llm()
        response = llm.invoke(lc_messages)
        content = response.content if hasattr(response, "content") else str(response)
        return LlmResponse(content=content.strip(), model=self._model_name, raw=response)

    def invoke(self, prompt: str, **kwargs) -> LlmResponse:
        llm = self._get_llm()
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        usage: dict = {}
        if hasattr(response, "response_metadata"):
            meta = response.response_metadata or {}
            token_usage = meta.get("usage", {})
            if token_usage:
                usage = {
                    "input_tokens": token_usage.get("input_tokens", 0),
                    "output_tokens": token_usage.get("output_tokens", 0),
                }

        return LlmResponse(
            content=content.strip(),
            model=self._model_name,
            usage=usage,
            raw=response,
        )

    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        llm = self._get_streaming_llm()
        for chunk in llm.stream(prompt):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                yield token

    def provider_name(self) -> str:
        return "anthropic"
