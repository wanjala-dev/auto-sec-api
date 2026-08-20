"""Helpers for logging deep-run events."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_deep_event(
    thread_id: str,
    event_type: str,
    *,
    status: str | None = None,
    agent_type: str | None = None,
    tool_name: str | None = None,
    payload: dict[str, Any] | None = None,
    prompt_id: str | None = None,
    prompt_version: str | None = None,
):
    """Create a DeepRunLog entry if the DeepRun exists.

    ``prompt_id`` / ``prompt_version`` carry the prompt half of the ADR 0032 D1
    configuration tuple. Optional and blank-by-default: a caller that cannot say
    which prompt version produced the row leaves it unattributed rather than
    guessing, and no existing caller has to change.
    """
    from infrastructure.persistence.ai.agents import models

    if not thread_id:
        return None
    try:
        run = models.DeepRun.objects.filter(thread_id=thread_id).first()
        if not run:
            return None
        return models.DeepRunLog.objects.create(
            deep_run=run,
            event_type=event_type,
            status=status or "",
            agent_type=agent_type or "",
            tool_name=tool_name or "",
            payload=payload or {},
            prompt_id=prompt_id or "",
            prompt_version=prompt_version or "",
        )
    except Exception:
        logger.warning("Skipping deep-run log event for thread %s", thread_id, exc_info=True)
        return None
