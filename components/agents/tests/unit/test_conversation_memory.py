"""Unit tests for the native conversation-memory loaders (LangChain 1.x).

These replaced ``ConversationBufferMemory`` / ``ConversationBufferWindowMemory``
(removed upstream in 1.x). Faked chat history — no DB, no LLM.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage, HumanMessage

from components.agents.infrastructure.adapters.langchain.memories.conversation_memory import (
    CompactingConversationMemory,
    SqlConversationMemory,
    SqlWindowConversationMemory,
)


class _FakeHistory:
    """Duck-typed stand-in for SqlMessageHistory."""

    def __init__(self, messages):
        self._messages = messages
        self.conversation_id = "conv-1"

    @property
    def messages(self):
        return list(self._messages)


def _turns(n):
    out = []
    for i in range(n):
        out.append(HumanMessage(content=f"q{i}"))
        out.append(AIMessage(content=f"a{i}"))
    return out


class TestSqlConversationMemory:
    def test_loads_full_buffer(self):
        memory = SqlConversationMemory(chat_memory=_FakeHistory(_turns(3)))
        assert len(memory.load_messages()) == 6

    def test_conversation_id_passthrough(self):
        memory = SqlConversationMemory(chat_memory=_FakeHistory([]))
        assert memory.conversation_id == "conv-1"

    def test_load_failure_degrades_to_empty(self):
        class _Broken:
            conversation_id = "conv-x"

            @property
            def messages(self):
                raise RuntimeError("db down")

        memory = SqlConversationMemory(chat_memory=_Broken())
        assert memory.load_messages() == []


class TestSqlWindowConversationMemory:
    def test_window_keeps_last_k_exchanges(self):
        memory = SqlWindowConversationMemory(chat_memory=_FakeHistory(_turns(5)), k=2)
        loaded = memory.load_messages()
        assert len(loaded) == 4
        assert loaded[0].content == "q3"
        assert loaded[-1].content == "a4"

    def test_short_history_is_untouched(self):
        memory = SqlWindowConversationMemory(chat_memory=_FakeHistory(_turns(1)), k=5)
        assert len(memory.load_messages()) == 2

    def test_k_floor_is_one(self):
        memory = SqlWindowConversationMemory(chat_memory=_FakeHistory(_turns(3)), k=0)
        assert len(memory.load_messages()) == 2


class _FakeCompactionLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)

        class _R:
            content = "summary of older turns"

        return _R()


class TestCompactingConversationMemory:
    def test_no_compaction_within_window(self):
        llm = _FakeCompactionLLM()
        memory = CompactingConversationMemory(chat_memory=_FakeHistory(_turns(2)), k=5, compaction_llm=llm)
        assert len(memory.load_messages()) == 4
        assert llm.calls == []

    def test_overflow_is_summarised_into_system_message(self):
        llm = _FakeCompactionLLM()
        memory = CompactingConversationMemory(chat_memory=_FakeHistory(_turns(6)), k=2, compaction_llm=llm)
        loaded = memory.load_messages()
        # 1 summary + window of 4
        assert len(loaded) == 5
        assert "summary of older turns" in loaded[0].content
        assert len(llm.calls) == 1

    def test_no_llm_degrades_to_plain_window(self):
        memory = CompactingConversationMemory(chat_memory=_FakeHistory(_turns(6)), k=2, compaction_llm=None)
        loaded = memory.load_messages()
        assert len(loaded) == 4

    def test_compaction_failure_never_raises(self):
        class _BoomLLM:
            def invoke(self, prompt):
                raise RuntimeError("llm down")

        memory = CompactingConversationMemory(chat_memory=_FakeHistory(_turns(6)), k=2, compaction_llm=_BoomLLM())
        loaded = memory.load_messages()
        assert len(loaded) == 4  # window survives, no summary
