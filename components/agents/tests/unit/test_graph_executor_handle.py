"""Unit tests for the LangChain 1.x ``_GraphExecutorHandle`` seam (base.py).

The handle adapts a ``create_agent`` graph to the legacy executor contract:
``{"input": q}`` in, ``{"output", "intermediate_steps"}`` out, with SQL-backed
history threaded into the graph input. These tests fake the graph — no LLM,
no DB.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from components.agents.infrastructure.adapters.langchain.base import _GraphExecutorHandle


class _FakeGraph:
    def __init__(self, result_messages):
        self.result_messages = result_messages
        self.calls = []

    def invoke(self, state, config=None):
        self.calls.append((state, config))
        return {"messages": list(state.get("messages", [])) + list(self.result_messages)}


class TestInputTranslation:
    def test_query_becomes_trailing_human_message(self):
        graph = _FakeGraph([AIMessage(content="hi")])
        handle = _GraphExecutorHandle(graph=graph)
        handle.invoke({"input": "what is up"})
        state, _ = graph.calls[0]
        assert isinstance(state["messages"][-1], HumanMessage)
        assert state["messages"][-1].content == "what is up"

    def test_history_is_prepended(self):
        history = [HumanMessage(content="earlier q"), AIMessage(content="earlier a")]
        graph = _FakeGraph([AIMessage(content="done")])
        handle = _GraphExecutorHandle(graph=graph, history_provider=lambda: history)
        handle.invoke({"input": "next"})
        state, _ = graph.calls[0]
        assert state["messages"][:2] == history
        assert state["messages"][-1].content == "next"

    def test_failing_history_provider_degrades_to_empty(self):
        def boom():
            raise RuntimeError("db down")

        graph = _FakeGraph([AIMessage(content="ok")])
        handle = _GraphExecutorHandle(graph=graph, history_provider=boom)
        result = handle.invoke({"input": "q"})
        state, _ = graph.calls[0]
        assert len(state["messages"]) == 1
        assert result["output"] == "ok"

    def test_non_message_history_entries_are_dropped(self):
        graph = _FakeGraph([AIMessage(content="ok")])
        handle = _GraphExecutorHandle(graph=graph, history_provider=lambda: ["junk", None, SystemMessage(content="s")])
        handle.invoke({"input": "q"})
        state, _ = graph.calls[0]
        assert len(state["messages"]) == 2  # SystemMessage + HumanMessage

    def test_recursion_limit_and_callbacks_in_config(self):
        graph = _FakeGraph([AIMessage(content="ok")])
        sentinel_cb = object()
        handle = _GraphExecutorHandle(graph=graph, callbacks=[sentinel_cb], recursion_limit=7)
        handle.invoke({"input": "q"})
        _, config = graph.calls[0]
        assert config["recursion_limit"] == 7
        assert config["callbacks"] == [sentinel_cb]


class TestOutputTranslation:
    def test_output_is_last_ai_message_without_tool_calls(self):
        messages = [
            AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
            ToolMessage(content="tool says", tool_call_id="1"),
            AIMessage(content="final answer"),
        ]
        handle = _GraphExecutorHandle(graph=_FakeGraph(messages))
        result = handle.invoke({"input": "q"})
        assert result["output"] == "final answer"
        assert result["input"] == "q"

    def test_intermediate_steps_pair_tool_calls_with_observations(self):
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"name": "list_findings", "args": {"limit": 3}, "id": "call-9"}],
            ),
            ToolMessage(content="3 findings", tool_call_id="call-9"),
            AIMessage(content="done"),
        ]
        handle = _GraphExecutorHandle(graph=_FakeGraph(messages))
        result = handle.invoke({"input": "q"})
        steps = result["intermediate_steps"]
        assert len(steps) == 1
        action, observation = steps[0]
        assert action.tool == "list_findings"
        assert action.tool_input == {"limit": 3}
        assert observation == "3 findings"

    def test_history_ai_messages_do_not_leak_into_steps(self):
        # Prior-turn AI messages carry no tool_calls, so reconstruction must
        # only reflect THIS run's tool activity.
        history = [HumanMessage(content="old"), AIMessage(content="old answer")]
        messages = [AIMessage(content="fresh answer")]
        handle = _GraphExecutorHandle(graph=_FakeGraph(messages), history_provider=lambda: history)
        result = handle.invoke({"input": "q"})
        assert result["intermediate_steps"] == []
        assert result["output"] == "fresh answer"
