import pytest

from components.knowledge.infrastructure.factories.llms import factory


def test_create_llm_delegates_to_builder(monkeypatch):
    called = {}

    def fake_builder(*, chat_args=None, **kwargs):
        called["builder"] = (chat_args, kwargs)
        return "llm-instance"

    monkeypatch.setitem(factory.LLMFactory.PROVIDERS["openai"], "llm", fake_builder)

    result = factory.LLMFactory.create_llm(provider="openai", streaming=False, chat_args="args", temperature=0.5)

    assert result == "llm-instance"
    assert called["builder"][0] == "args"
    assert called["builder"][1]["temperature"] == 0.5


def test_create_llm_streaming(monkeypatch):
    called = {}

    def fake_stream(*, chat_args=None, **kwargs):
        called["stream"] = (chat_args, kwargs)
        return "stream-llm"

    monkeypatch.setitem(factory.LLMFactory.PROVIDERS["openai"], "streaming", fake_stream)

    result = factory.LLMFactory.create_llm(provider="openai", streaming=True, chat_args="args")

    assert result == "stream-llm"
    assert called["stream"][0] == "args"


def test_create_llm_invalid_provider():
    with pytest.raises(ValueError):
        factory.LLMFactory.create_llm(provider="unknown")


def test_get_provider_info_lists_supported_models():
    info = factory.LLMFactory.get_provider_info("azure")
    assert info["provider"] == "azure"
    assert info["supports_streaming"] is True
    assert "gpt-4" in info["available_models"]
