"""Helpers for logging deep-run events."""
from __future__ import annotations

from typing import Any, Optional

import logging

logger = logging.getLogger(__name__)


def log_deep_event(
    thread_id: str,
    event_type: str,
    *,
    status: Optional[str] = None,
    agent_type: Optional[str] = None,
    tool_name: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
):
    """Create a DeepRunLog entry if the DeepRun exists."""
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
        )
    except Exception:
        logger.warning("Skipping deep-run log event for thread %s", thread_id, exc_info=True)
        return None
