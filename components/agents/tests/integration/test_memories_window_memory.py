from types import SimpleNamespace

import components.agents.infrastructure.adapters.langchain.memories.window_memory as wm


class DummyMemory:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_window_buffer_memory_builder_uses_conversation_id(monkeypatch):
    captured = {}

    def fake_cbwm(**kwargs):
        captured.update(kwargs)
        return DummyMemory(**kwargs)

    monkeypatch.setattr(wm, "ConversationBufferWindowMemory", fake_cbwm)
    chat_args = SimpleNamespace(conversation_id="conv-1")

    memory = wm.window_buffer_memory_builder(chat_args)

    assert isinstance(memory, DummyMemory)
    assert captured["chat_memory"].conversation_id == "conv-1"
    assert captured["k"] == 2


def test_window_buffer_memory_builder_with_custom_k(monkeypatch):
    captured = {}

    def fake_cbwm(**kwargs):
        captured.update(kwargs)
        return DummyMemory(**kwargs)

    monkeypatch.setattr(wm, "ConversationBufferWindowMemory", fake_cbwm)
    chat_args = SimpleNamespace(conversation_id="conv-2")

    memory = wm.window_buffer_memory_builder_with_k(chat_args, k=5)

    assert memory.kwargs["k"] == 5
