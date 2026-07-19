"""OpenAI LLM adapter — wraps apps.ai.llms.chatopenai behind LlmPort."""

from __future__ import annotations

from typing import Iterator

from components.knowledge.application.ports.llm_port import LlmPort, LlmResponse


class OpenAILlmAdapter(LlmPort):
    """Adapter for the OpenAI ChatGPT backend."""

    def __init__(self, *, model_name: str = "gpt-3.5-turbo", temperature: float = 0.7) -> None:
        self._model_name = model_name
        self._temperature = temperature

    def _build_llm(self, streaming: bool = False):
        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory
        return LLMFactory.create_llm(
            provider="openai",
            streaming=streaming,
            model_name=self._model_name,
            temperature=self._temperature,
        )

    def invoke(self, prompt: str, **kwargs) -> LlmResponse:
        llm = self._build_llm(streaming=False)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return LlmResponse(
            content=content.strip(),
            model=self._model_name,
            raw=response,
        )

    def chat(self, messages: list[dict[str, str]], **kwargs) -> LlmResponse:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        role_map = {
            "system": SystemMessage,
            "user": HumanMessage,
            "human": HumanMessage,
            "assistant": AIMessage,
            "ai": AIMessage,
        }
        lc_messages = []
        for msg in messages:
            cls = role_map.get(msg.get("role", "user"), HumanMessage)
            lc_messages.append(cls(content=msg.get("content", "")))

        llm = self._build_llm(streaming=False)
        response = llm.invoke(lc_messages)
        content = response.content if hasattr(response, "content") else str(response)
        return LlmResponse(
            content=content.strip(),
            model=self._model_name,
            raw=response,
        )

    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        llm = self._build_llm(streaming=True)
        for chunk in llm.stream(prompt):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                yield token

    def provider_name(self) -> str:
        return "openai"
