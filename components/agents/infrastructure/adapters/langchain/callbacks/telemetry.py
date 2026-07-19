"""
Telemetry callback handler for LangChain agents.

Collects aggregate metrics about LLM, tool, and chain usage for a single
agent execution lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.outputs import LLMResult


@dataclass
class TokenUsage:
    """Aggregate token usage counters."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int, total_tokens: int) -> None:
        """Accumulate token usage values."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens


class TelemetryCallback(BaseCallbackHandler):
    """Track LangChain agent telemetry and provide summary snapshots."""

    def __init__(self, agent_id: str, *, cost_tracker=None):
        """Create a new telemetry handler for the given agent."""
        self.agent_id = agent_id
        self.cost_tracker = cost_tracker
        self.reset()

    def reset(self) -> None:
        """Reset all counters and timers for a fresh execution."""
        self.started_at = datetime.now()
        self._started_at_monotonic = time.monotonic()

        self.llm_calls = 0
        self.tool_calls = 0
        self.chain_calls = 0
        self.agent_actions = 0

        self.errors = {
            "llm": 0,
            "tool": 0,
            "chain": 0,
            "agent": 0,
        }
        self.token_usage = TokenUsage()
        self.tool_usage: Dict[str, int] = {}
        self.model_usage: Dict[str, int] = {}
        self.tool_events: List[Dict[str, Any]] = []
        self._tool_event_by_run_id: Dict[str, Dict[str, Any]] = {}

        self._durations_ms = {
            "llm": 0,
            "tool": 0,
            "chain": 0,
        }
        self._llm_start_times: Dict[str, float] = {}
        self._tool_start_times: Dict[str, float] = {}
        self._chain_start_times: Dict[str, float] = {}

    def summary(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot of telemetry stats."""
        elapsed_ms = int((time.monotonic() - self._started_at_monotonic) * 1000)
        return {
            "agent_id": self.agent_id,
            "started_at": self.started_at.isoformat(),
            "elapsed_ms": elapsed_ms,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "chain_calls": self.chain_calls,
            "agent_actions": self.agent_actions,
            "errors": dict(self.errors),
            "tokens": {
                "input_tokens": self.token_usage.input_tokens,
                "output_tokens": self.token_usage.output_tokens,
                "total_tokens": self.token_usage.total_tokens,
            },
            "durations_ms": dict(self._durations_ms),
            "tools": dict(self.tool_usage),
            "models": dict(self.model_usage),
            "tool_events": list(self.tool_events),
        }

    def on_llm_start(  # type: ignore[override]
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle the start of an LLM call."""
        self.llm_calls += 1
        run_id = _extract_run_id(args, kwargs)
        if run_id:
            self._llm_start_times[run_id] = time.monotonic()

    def on_llm_end(  # type: ignore[override]
        self,
        response: LLMResult,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle the completion of an LLM call."""
        run_id = _extract_run_id(args, kwargs)
        if run_id in self._llm_start_times:
            duration = time.monotonic() - self._llm_start_times.pop(run_id)
            self._durations_ms["llm"] += int(duration * 1000)
        self._accumulate_token_usage(response)

    def on_llm_error(  # type: ignore[override]
        self,
        error: BaseException,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle LLM errors."""
        self.errors["llm"] += 1

    def on_chain_start(  # type: ignore[override]
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle the start of a chain execution."""
        self.chain_calls += 1
        run_id = _extract_run_id(args, kwargs)
        if run_id:
            self._chain_start_times[run_id] = time.monotonic()

    def on_chain_end(  # type: ignore[override]
        self,
        outputs: Dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle the end of a chain execution."""
        run_id = _extract_run_id(args, kwargs)
        if run_id in self._chain_start_times:
            duration = time.monotonic() - self._chain_start_times.pop(run_id)
            self._durations_ms["chain"] += int(duration * 1000)

    def on_chain_error(  # type: ignore[override]
        self,
        error: BaseException,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle chain errors."""
        self.errors["chain"] += 1

    def on_tool_start(  # type: ignore[override]
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle the start of a tool invocation."""
        self.tool_calls += 1
        tool_name = _extract_tool_name(serialized, kwargs)
        if tool_name:
            self.tool_usage[tool_name] = self.tool_usage.get(tool_name, 0) + 1
        run_id = _extract_run_id(args, kwargs)
        if run_id:
            self._tool_start_times[run_id] = time.monotonic()
            self._tool_event_by_run_id[run_id] = {
                "tool": tool_name,
                "input_chars": len(input_str) if isinstance(input_str, str) else 0,
                "input_preview": (input_str[:200] + "...") if isinstance(input_str, str) and len(input_str) > 200 else input_str,
            }

    def on_tool_end(  # type: ignore[override]
        self,
        output: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle the completion of a tool invocation."""
        run_id = _extract_run_id(args, kwargs)
        if run_id in self._tool_start_times:
            duration = time.monotonic() - self._tool_start_times.pop(run_id)
            self._durations_ms["tool"] += int(duration * 1000)
        event = self._tool_event_by_run_id.pop(run_id, None)
        if event is None:
            event = {"tool": _extract_tool_name(None, kwargs)}
        event["output_chars"] = len(output) if isinstance(output, str) else 0
        if len(self.tool_events) < 50:
            self.tool_events.append(event)

    def on_tool_error(  # type: ignore[override]
        self,
        error: BaseException,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Handle tool errors."""
        self.errors["tool"] += 1

    def on_agent_action(  # type: ignore[override]
        self,
        action: AgentAction,
        **kwargs: Any,
    ) -> Any:
        """Handle agent action events."""
        self.agent_actions += 1
        if action.tool:
            self.tool_usage[action.tool] = self.tool_usage.get(action.tool, 0) + 1

    def on_agent_finish(  # type: ignore[override]
        self,
        finish: AgentFinish,
        **kwargs: Any,
    ) -> Any:
        """Handle agent finish events."""
        return None

    def _accumulate_token_usage(self, response: LLMResult) -> None:
        usage = _extract_usage_from_response(response)
        if not usage:
            return
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        self.token_usage.add(input_tokens, output_tokens, total_tokens)

        model_name = usage.get("model")
        if model_name:
            self.model_usage[model_name] = self.model_usage.get(model_name, 0) + 1

        # Feed the cost tracker if one was attached
        if self.cost_tracker is not None:
            try:
                self.cost_tracker.record_llm_call(
                    model=model_name or "unknown",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            except Exception:
                pass  # Cost tracking is best-effort


def _extract_run_id(args: Any, kwargs: Dict[str, Any]) -> Optional[str]:
    """Resolve the run_id from positional or keyword arguments."""
    if args:
        return args[0]
    return kwargs.get("run_id")


def _extract_tool_name(serialized: Optional[Dict[str, Any]], kwargs: Dict[str, Any]) -> Optional[str]:
    """Return the best-guess tool name for telemetry attribution."""
    if isinstance(serialized, dict):
        name = serialized.get("name") or serialized.get("id")
        if name:
            return name
    return kwargs.get("name") or kwargs.get("tool") or kwargs.get("tool_name")


def _extract_usage_from_response(response: LLMResult) -> Dict[str, Any]:
    """Pull token usage details from the LLM response."""
    usage = _extract_usage_from_llm_output(response)
    if usage:
        return usage
    return _extract_usage_from_generations(response)


def _extract_usage_from_llm_output(response: LLMResult) -> Dict[str, Any]:
    """Extract token usage from LLMResult.llm_output if present."""
    output = getattr(response, "llm_output", None)
    if not isinstance(output, dict):
        return {}
    token_usage = output.get("token_usage") or output.get("usage") or {}
    return _normalize_token_usage(token_usage, output.get("model_name"))


def _extract_usage_from_generations(response: LLMResult) -> Dict[str, Any]:
    """Extract token usage from generation metadata when llm_output is absent."""
    generations = getattr(response, "generations", None) or []
    totals = TokenUsage()
    model_name = None
    for generation_list in generations:
        for generation in generation_list:
            info = getattr(generation, "generation_info", None) or {}
            token_usage = info.get("token_usage") or info.get("usage")
            if token_usage:
                normalized = _normalize_token_usage(token_usage, info.get("model_name"))
                totals.add(
                    normalized.get("input_tokens", 0),
                    normalized.get("output_tokens", 0),
                    normalized.get("total_tokens", 0),
                )
                if not model_name:
                    model_name = normalized.get("model")
    if totals.total_tokens == 0 and totals.input_tokens == 0 and totals.output_tokens == 0:
        return {}
    return {
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "total_tokens": totals.total_tokens,
        "model": model_name,
    }


def _normalize_token_usage(token_usage: Any, model_name: Optional[str]) -> Dict[str, Any]:
    """Normalize token usage fields from different provider formats."""
    if not isinstance(token_usage, dict):
        return {}
    input_tokens = _safe_int(
        token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
    )
    output_tokens = _safe_int(
        token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
    )
    total_tokens = _safe_int(
        token_usage.get("total_tokens") or token_usage.get("total") or (input_tokens + output_tokens)
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "model": model_name,
    }


def _safe_int(value: Any) -> int:
    """Convert value to int, returning 0 on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
