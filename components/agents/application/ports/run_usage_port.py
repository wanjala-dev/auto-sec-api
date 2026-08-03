"""Port: persist an execution-cost snapshot onto a run's ``state['usage']``.

``ExecutionCostTracker`` accumulates token/cost usage during an agent run
(application-layer, framework-free) and, at the end, merges that snapshot into
the ``state`` JSON of either an ``AgentExecution`` (per-execution) or a
``DeepRun`` (per-thread). Both writes used to reach ``infrastructure.persistence.ai``
ORM directly from the application layer — a Rule-2 violation (dependencies point
inward). This port is the sanctioned write seam so the tracker depends on an
agents-context interface, and the ORM lives in the adapter.

Both methods are best-effort by contract: a missing row is a no-op (the run may
have been pruned), and an ORM failure is swallowed by the adapter — merging a
usage snapshot must never break a run that already produced its answer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RunUsagePort(ABC):
    """Merge a usage snapshot into a run's ``state['usage']`` (best-effort)."""

    @abstractmethod
    def merge_execution_usage(self, execution_id: str | int, usage: dict[str, Any]) -> None:
        """Merge ``usage`` into ``AgentExecution.state['usage']`` for the row.

        No-op when the execution row does not exist. Errors are swallowed —
        cost tracking must never break the execution.
        """

    @abstractmethod
    def merge_deep_run_usage(self, thread_id: str, usage: dict[str, Any]) -> None:
        """Merge ``usage`` into ``DeepRun.state['usage']`` for the thread.

        No-op when the deep-run row does not exist. Errors are swallowed —
        cost tracking must never break the run.
        """
