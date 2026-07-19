"""Token and cost tracking for agent executions.

Accumulates token usage and estimated cost during an agent run. The tracker
is thread-safe and designed to be passed into LangChain callbacks or
updated manually after each LLM call.

Usage::

    tracker = ExecutionCostTracker()

    # After each LLM call:
    tracker.record_llm_call(
        model="gpt-4o",
        input_tokens=1500,
        output_tokens=400,
        cost_usd=0.023,
    )

    # At end of execution:
    tracker.persist_to_execution(execution_id)
    # or
    tracker.persist_to_deep_run(thread_id)

The snapshot is stored in the existing ``state`` JSONField under the key
``"usage"``, avoiding any schema migration.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0


@dataclass
class ExecutionCostTracker:
    """Accumulates token usage and estimated cost for an agent execution."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _by_model: dict[str, _ModelUsage] = field(default_factory=dict)
    _total_input: int = 0
    _total_output: int = 0
    _total_cost: float = 0.0
    _total_calls: int = 0

    def record_llm_call(
        self,
        *,
        model: str = "unknown",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record a single LLM API call."""
        with self._lock:
            usage = self._by_model.setdefault(model, _ModelUsage())
            usage.input_tokens += input_tokens
            usage.output_tokens += output_tokens
            usage.cache_read_tokens += cache_read_tokens
            usage.cache_write_tokens += cache_write_tokens
            usage.cost_usd += cost_usd
            usage.call_count += 1

            self._total_input += input_tokens
            self._total_output += output_tokens
            self._total_cost += cost_usd
            self._total_calls += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of accumulated usage."""
        with self._lock:
            by_model = {}
            for model, usage in self._by_model.items():
                by_model[model] = {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "cost_usd": round(usage.cost_usd, 6),
                    "call_count": usage.call_count,
                }
            return {
                "total_input_tokens": self._total_input,
                "total_output_tokens": self._total_output,
                "total_tokens": self._total_input + self._total_output,
                "total_cost_usd": round(self._total_cost, 6),
                "total_llm_calls": self._total_calls,
                "by_model": by_model,
            }

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return self._total_input + self._total_output

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return self._total_cost

    def persist_to_execution(self, execution_id: str | int) -> None:
        """Merge usage snapshot into AgentExecution.state['usage']."""
        try:
            from infrastructure.persistence.ai.agents.models import AgentExecution

            execution = AgentExecution.objects.filter(id=execution_id).first()
            if not execution:
                return
            state = dict(execution.state or {})
            state["usage"] = self.snapshot()
            AgentExecution.objects.filter(id=execution_id).update(state=state)
        except Exception:
            logger.warning("Failed to persist cost tracker to execution %s", execution_id, exc_info=True)

    def persist_to_deep_run(self, thread_id: str) -> None:
        """Merge usage snapshot into DeepRun.state['usage']."""
        try:
            from infrastructure.persistence.ai.agents.models import DeepRun

            run = DeepRun.objects.filter(thread_id=thread_id).first()
            if not run:
                return
            state = dict(run.state or {})
            state["usage"] = self.snapshot()
            DeepRun.objects.filter(thread_id=thread_id).update(state=state)
        except Exception:
            logger.warning("Failed to persist cost tracker to deep run %s", thread_id, exc_info=True)
