"""Test harness for `BaseAgent` subclasses (ADR 0003).

Lets you write fast, deterministic agent tests without paying for real
LLM calls in CI. Mocks the LLM's tool selection and the tools' return
values, then asserts on which tools were called and with what arguments.

Example usage::

    class BlogAgentTests(AgentTestCase):
        def test_count_articles(self):
            agent = self.make_agent(
                BlogAgent,
                workspace_id="ws-1",
                user_id="user-1",
            )
            self.mock_tool_returns("get_news_articles", "5 articles")
            self.mock_llm_chooses("get_news_articles", "all articles")
            result = agent.execute("how many articles do I have")
            self.assert_tool_called("get_news_articles")
            self.assertIn("5", result)

This is intentionally minimal — it doesn't try to fake the full
ReAct loop, it stubs `agent_executor.invoke` directly so each test
controls exactly which tool gets called and what it returns. If you need
multi-step reasoning tests, use the `script_tool_calls(...)` helper to
queue multiple selections.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from django.test import TestCase


class _ScriptedExecutor:
    """Stand-in for `AgentExecutor` that scripts tool selection.

    Each call to `.invoke({"input": query})` consumes the next entry
    from the script queue, calls the matching `Tool.func`, captures the
    invocation, and returns a dict shaped like the real executor's
    output.
    """

    def __init__(self, tools, script, captured_calls):
        self._tools_by_name = {tool.name: tool for tool in tools}
        self._script = list(script)
        self._captured = captured_calls

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = inputs.get("input", "")
        if not self._script:
            return {"input": query, "output": "(no scripted tool call)"}
        tool_name, tool_input = self._script.pop(0)
        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            raise AssertionError(
                f"Scripted tool '{tool_name}' not found on agent. "
                f"Available: {sorted(self._tools_by_name)}"
            )
        result = tool.func(tool_input) if tool_input is not None else tool.func()
        self._captured.append((tool_name, tool_input, result))
        return {"input": query, "output": str(result)}


class AgentTestCase(TestCase):
    """Base test case that monkeypatches the agent executor + LLM.

    Use `make_agent(cls, ...)` to construct an agent with a fake LLM and
    a scripted executor. Use `mock_tool_returns(name, value)` to control
    what each tool returns. Use `mock_llm_chooses(name, args)` (or
    `script_tool_calls([(name, args), ...])` for multi-step) to queue
    the LLM's tool selections.
    """

    def setUp(self) -> None:  # noqa: D401
        super().setUp()
        self._tool_returns: Dict[str, Any] = {}
        self._scripted_calls: List[Tuple[str, Optional[str]]] = []
        self._captured_calls: List[Tuple[str, Optional[str], Any]] = []

    # ── Construction ───────────────────────────────────────────────

    def make_agent(
        self,
        agent_cls,
        *,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        **overrides,
    ):
        """Build an instance of `agent_cls` with the LLM + executor faked.

        Defaults all three IDs to fresh UUIDs because BaseAgent's
        downstream code (memory service, telemetry) sometimes hits the
        DB with these values and would fail on non-UUID strings. Override
        any of them when you need a specific known-good ID.

        We also patch `_create_agent_executor` to a no-op so the
        construction never tries to wire a real LangChain ReAct agent
        with the fake LLM (which would fail because MagicMock doesn't
        implement the LLM interface). The scripted executor is then
        installed manually below.
        """

        agent_id = agent_id or str(uuid.uuid4())
        user_id = user_id or str(uuid.uuid4())
        workspace_id = workspace_id or str(uuid.uuid4())

        fake_llm = MagicMock(name="fake_llm")
        fake_provider = MagicMock(name="fake_llm_provider")
        fake_provider.get_llm = MagicMock(return_value=fake_llm)

        # Stub the things `BaseAgent.__init__` reaches into the DB for so
        # tests don't need a real Agent row, real workspace row, or
        # real OpenAI credentials:
        #   - get_agent_memory_service hits Agent.objects.get(agent_id=...)
        #   - _create_agent_executor builds a real ReAct executor against
        #     the fake LLM, which doesn't implement the LLM interface
        from components.agents.infrastructure.adapters.langchain import (
            base as base_module,
        )

        fake_memory_service = MagicMock(name="fake_memory_service")
        fake_memory_service.get_memory = MagicMock(return_value=MagicMock())
        fake_memory_service.get_conversation_id = MagicMock(return_value=None)

        with patch.object(
            base_module,
            "get_agent_memory_service",
            return_value=fake_memory_service,
        ), patch.object(
            agent_cls,
            "_create_agent_executor",
            lambda self_inner: None,
            create=False,
        ):
            agent = agent_cls(
                agent_id=agent_id,
                user_id=user_id,
                workspace_id=workspace_id,
                llm_provider=fake_provider,
                **overrides,
            )

        # Install the scripted executor.
        agent.agent_executor = _ScriptedExecutor(
            agent.tools,
            self._scripted_calls,
            self._captured_calls,
        )

        # Swap any mocked tool's .func.
        for tool in agent.tools:
            if tool.name in self._tool_returns:
                preset = self._tool_returns[tool.name]
                tool.func = lambda *_args, _preset=preset, **_kw: _preset

        return agent

    # ── Scripting helpers ──────────────────────────────────────────

    def mock_tool_returns(self, tool_name: str, return_value: Any) -> None:
        """Pre-stub a tool's `.func` to return `return_value`.

        Must be called BEFORE `make_agent` so the substitution happens
        during agent construction.
        """
        self._tool_returns[tool_name] = return_value

    def mock_llm_chooses(self, tool_name: str, tool_input: Optional[str] = None) -> None:
        """Queue one scripted tool selection. Equivalent to
        `script_tool_calls([(tool_name, tool_input)])` but additive — call
        multiple times to queue a sequence.
        """
        self._scripted_calls.append((tool_name, tool_input))

    def script_tool_calls(self, calls: List[Tuple[str, Optional[str]]]) -> None:
        """Replace the script with a sequence of (tool_name, input) tuples."""
        self._scripted_calls.clear()
        self._scripted_calls.extend(calls)

    # ── Assertions ────────────────────────────────────────────────

    def assert_tool_called(self, tool_name: str) -> None:
        called = [name for name, _, _ in self._captured_calls]
        self.assertIn(
            tool_name,
            called,
            msg=f"Expected tool '{tool_name}' to be called. Called: {called}",
        )

    def assert_tool_called_with(self, tool_name: str, expected_input: str) -> None:
        for name, tool_input, _ in self._captured_calls:
            if name == tool_name and tool_input == expected_input:
                return
        raise AssertionError(
            f"Expected tool '{tool_name}' called with '{expected_input}'. "
            f"Captured: {self._captured_calls}"
        )

    def assert_no_tools_called(self) -> None:
        if self._captured_calls:
            raise AssertionError(
                f"Expected no tool calls. Captured: {self._captured_calls}"
            )

    def captured_calls(self) -> List[Tuple[str, Optional[str], Any]]:
        return list(self._captured_calls)
