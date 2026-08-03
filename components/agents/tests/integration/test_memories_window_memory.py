"""Tests for the window-memory builders.

LangChain 1.x migration (2026-07-19) removed ``ConversationBufferWindowMemory``;
the builders now construct the native ``SqlWindowConversationMemory`` loader
(``memories/conversation_memory.py``) over a ``SqlMessageHistory``. The builder
signatures are unchanged (``chat_memory=`` + ``k=``), so we monkeypatch the new
constructor to capture the wiring the builders perform.
"""

from types import SimpleNamespace

import components.agents.infrastructure.adapters.langchain.memories.window_memory as wm


class DummyMemory:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_window_buffer_memory_builder_uses_conversation_id(monkeypatch):
    captured = {}

    def fake_window_memory(**kwargs):
        captured.update(kwargs)
        return DummyMemory(**kwargs)

    monkeypatch.setattr(wm, "SqlWindowConversationMemory", fake_window_memory)
    chat_args = SimpleNamespace(conversation_id="conv-1")

    memory = wm.window_buffer_memory_builder(chat_args)

    assert isinstance(memory, DummyMemory)
    assert captured["chat_memory"].conversation_id == "conv-1"
    assert captured["k"] == 2


def test_window_buffer_memory_builder_with_custom_k(monkeypatch):
    captured = {}

    def fake_window_memory(**kwargs):
        captured.update(kwargs)
        return DummyMemory(**kwargs)

    monkeypatch.setattr(wm, "SqlWindowConversationMemory", fake_window_memory)
    chat_args = SimpleNamespace(conversation_id="conv-2")

    memory = wm.window_buffer_memory_builder_with_k(chat_args, k=5)

    assert memory.kwargs["k"] == 5
