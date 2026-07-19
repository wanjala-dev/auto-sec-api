"""LangGraph StateGraph-based agent runner.

Replaces LangChain's legacy ``AgentExecutor`` with a modern LangGraph
``StateGraph`` for standard workspace chat agents.  Benefits:

- Explicit control flow (nodes + edges vs. opaque loop)
- Built-in streaming support
- Better error recovery (retry individual nodes)
- Conditional branching for multi-path reasoning

Agents can opt in by setting ``config["use_langgraph"] = True`` or
by calling ``build_graph_executor`` instead of ``_create_agent_executor``.
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, TypedDict

# LangChain 1.x — `langchain.schema` / `langchain.tools` re-export shims removed;
# import from langchain_core directly.
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import Tool as LangChainTool

logger = logging.getLogger(__name__)


# ── Graph State ──────────────────────────────────────────────────────


class AgentGraphState(TypedDict, total=False):
    """Shared state flowing through the agent graph."""

    messages: Annotated[list[BaseMessage], operator.add]
    tool_calls: list[dict[str, Any]]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    final_answer: str
    iteration_count: int
    error: str | None


# ── Graph Builder ────────────────────────────────────────────────────


def build_graph_executor(
    *,
    llm,
    tools: list[LangChainTool],
    system_prompt: str = "",
    max_iterations: int = 15,
    callbacks: list | None = None,
):
    """Build a LangGraph StateGraph that mirrors ReAct agent behaviour.

    Returns a compiled graph that can be invoked with::

        result = graph.invoke({"messages": [HumanMessage(content="...")]})
        answer = result["final_answer"]
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        logger.warning("langgraph not installed — cannot build graph executor. Install with: pip install langgraph")
        return None

    tool_map = {tool.name: tool for tool in tools}

    # ── Node: reason ─────────────────────────────────────────────────

    def reason_node(state: AgentGraphState) -> dict:
        """Call LLM to decide next action or produce final answer."""
        messages = state.get("messages", [])
        iteration = state.get("iteration_count", 0)

        if iteration >= max_iterations:
            return {
                "final_answer": "I've reached my reasoning limit. Here's what I have so far based on the conversation.",
                "iteration_count": iteration,
            }

        # Build messages list with system prompt
        llm_messages: list[BaseMessage] = []
        if system_prompt:
            llm_messages.append(SystemMessage(content=system_prompt))
        llm_messages.extend(messages)

        try:
            response = llm.bind_tools(tools).invoke(llm_messages, config={"callbacks": callbacks or []})
        except Exception as e:
            return {"error": str(e), "iteration_count": iteration + 1}

        # Check for tool calls
        tool_calls = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_calls = [
                {
                    "name": tc["name"],
                    "args": tc["args"],
                    "id": tc.get("id", ""),
                }
                for tc in response.tool_calls
            ]

        new_messages = [response] if isinstance(response, BaseMessage) else [AIMessage(content=str(response))]

        result: dict[str, Any] = {
            "messages": new_messages,
            "tool_calls": tool_calls,
            "iteration_count": iteration + 1,
        }

        # If no tool calls, the LLM produced a final answer
        if not tool_calls:
            content = response.content if hasattr(response, "content") else str(response)
            result["final_answer"] = content

        return result

    # ── Node: execute tools ──────────────────────────────────────────

    def tool_node(state: AgentGraphState) -> dict:
        """Execute pending tool calls and return results."""
        tool_calls = state.get("tool_calls", [])
        results: list[dict[str, Any]] = []
        result_messages: list[BaseMessage] = []

        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool = tool_map.get(tool_name)

            if tool is None:
                error_msg = f"Tool '{tool_name}' not found."
                results.append({"tool": tool_name, "error": error_msg})
                result_messages.append(HumanMessage(content=f"Tool error: {error_msg}"))
                continue

            try:
                if isinstance(tool_args, dict):
                    output = tool.invoke(tool_args)
                else:
                    output = tool.invoke(str(tool_args))
                results.append({"tool": tool_name, "output": str(output)})
                result_messages.append(HumanMessage(content=f"Tool '{tool_name}' result:\n{output}"))
            except Exception as e:
                results.append({"tool": tool_name, "error": str(e)})
                result_messages.append(HumanMessage(content=f"Tool '{tool_name}' error: {e}"))

        return {
            "messages": result_messages,
            "tool_results": results,
            "tool_calls": [],  # Clear pending calls
        }

    # ── Routing ──────────────────────────────────────────────────────

    def should_continue(state: AgentGraphState) -> str:
        """Route: if tool_calls pending → tools, else → end."""
        if state.get("error"):
            return END
        if state.get("final_answer"):
            return END
        if state.get("tool_calls"):
            return "tools"
        return END

    # ── Build Graph ──────────────────────────────────────────────────

    graph = StateGraph(AgentGraphState)
    graph.add_node("reason", reason_node)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("reason")
    graph.add_conditional_edges("reason", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "reason")  # After tools, reason again

    return graph.compile()
