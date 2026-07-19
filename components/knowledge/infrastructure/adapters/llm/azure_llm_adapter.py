"""Azure OpenAI LLM adapter — wraps apps.ai.llms.azure behind LlmPort."""

from __future__ import annotations

from typing import Iterator

from components.knowledge.application.ports.llm_port import LlmPort, LlmResponse


class AzureLlmAdapter(LlmPort):
    """Adapter for the Azure OpenAI backend."""

    def __init__(self, *, model_name: str | None = None, temperature: float = 0.7) -> None:
        self._model_name = model_name
        self._temperature = temperature

    def _build_llm(self, streaming: bool = False):
        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory
        kwargs = {"temperature": self._temperature}
        if self._model_name:
            kwargs["model_name"] = self._model_name
        return LLMFactory.create_llm(provider="azure", streaming=streaming, **kwargs)

    def invoke(self, prompt: str, **kwargs) -> LlmResponse:
        llm = self._build_llm(streaming=False)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return LlmResponse(
            content=content.strip(),
            model=self._model_name or "azure",
            raw=response,
        )

    def chat(self, messages: list[dict[str, str]], **kwargs) -> LlmResponse:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        role_map = {"system": SystemMessage, "user": HumanMessage, "human": HumanMessage, "assistant": AIMessage, "ai": AIMessage}
        lc_messages = [role_map.get(m.get("role", "user"), HumanMessage)(content=m.get("content", "")) for m in messages]

        llm = self._build_llm(streaming=False)
        response = llm.invoke(lc_messages)
        content = response.content if hasattr(response, "content") else str(response)
        return LlmResponse(content=content.strip(), model=self._model_name or "azure", raw=response)

    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        llm = self._build_llm(streaming=True)
        for chunk in llm.stream(prompt):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                yield token

    def provider_name(self) -> str:
        return "azure"
