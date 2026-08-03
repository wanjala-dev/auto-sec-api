"""ORM adapter implementing :class:`RunUsagePort`.

Merges an :class:`ExecutionCostTracker` usage snapshot into the ``state`` JSON of
an ``AgentExecution`` or ``DeepRun``. Both writes are best-effort: a missing row
is a no-op, and any ORM error is logged and swallowed — persisting a cost
snapshot must never break a run that already produced its answer.

The read-then-``.update()`` shape (rather than ``instance.save()``) matches the
prior inline implementation exactly: it merges the ``usage`` key while leaving
the rest of ``state`` untouched, without racing on other ``state`` fields.
"""

from __future__ import annotations

import logging
from typing import Any

from components.agents.application.ports.run_usage_port import RunUsagePort

logger = logging.getLogger(__name__)


class OrmRunUsageRepository(RunUsagePort):
    def merge_execution_usage(self, execution_id: str | int, usage: dict[str, Any]) -> None:
        try:
            from infrastructure.persistence.ai.agents.models import AgentExecution

            execution = AgentExecution.objects.filter(id=execution_id).first()
            if not execution:
                return
            state = dict(execution.state or {})
            state["usage"] = usage
            AgentExecution.objects.filter(id=execution_id).update(state=state)
        except Exception:
            logger.warning("Failed to persist cost tracker to execution %s", execution_id, exc_info=True)

    def merge_deep_run_usage(self, thread_id: str, usage: dict[str, Any]) -> None:
        try:
            from infrastructure.persistence.ai.agents.models import DeepRun

            run = DeepRun.objects.filter(thread_id=thread_id).first()
            if not run:
                return
            state = dict(run.state or {})
            state["usage"] = usage
            DeepRun.objects.filter(thread_id=thread_id).update(state=state)
        except Exception:
            logger.warning("Failed to persist cost tracker to deep run %s", thread_id, exc_info=True)
