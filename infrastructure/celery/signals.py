"""Celery signal handlers — DB connection lifecycle + structured task telemetry.

Two responsibilities live here:

1. **DB connection hygiene.** Workers fork from the master process and inherit
   open connections; without `close_old_connections()` on prerun/postrun, those
   leak and eventually exhaust Postgres.

2. **Structured task telemetry.** Every task emits a one-line ``task.start`` /
   ``task.end`` / ``task.fail`` log with ``task_id``, ``task_name``, ``state``,
   ``duration_ms``, and ``retries``. This is what makes incidents diagnosable in
   prod — see celery-tasks skill rule 7. Pair with each task's own narrative
   logs (rule 10).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_process_init,
)
from django.db import close_old_connections


logger = logging.getLogger("celery.tasks")

# Per-process map of task_id -> perf_counter at start. Reset on worker fork so
# we don't bleed state across forked workers. Lookups are O(1) and entries are
# popped on postrun/failure, so this never grows beyond the active task set.
_task_start_times: dict[str, float] = {}


@worker_process_init.connect
def _on_worker_process_init(**_kwargs: Any) -> None:
    """Drop inherited DB connections so each worker opens its own."""
    close_old_connections()
    _task_start_times.clear()


@task_prerun.connect
def _on_task_prerun(task_id: str, task: Any, *_args: Any, **_kwargs: Any) -> None:
    _task_start_times[task_id] = time.perf_counter()
    task_name = getattr(task, "name", "unknown")
    # Render contextual fields directly into the message so plain text-log
    # readers (the demo's default Celery formatter, `docker logs`) see them
    # too — `extra=` alone is invisible without a JSON formatter, which we
    # don't run in this environment yet. Structured backends (Sentry,
    # Logfire) still consume the extra dict.
    logger.info(
        "task.start task_id=%s task_name=%s",
        task_id,
        task_name,
        extra={"task_id": task_id, "task_name": task_name},
    )


@task_postrun.connect
def _on_task_postrun(
    task_id: str,
    task: Any,
    state: str | None = None,
    *_args: Any,
    **_kwargs: Any,
) -> None:
    started = _task_start_times.pop(task_id, None)
    duration_ms = round((time.perf_counter() - started) * 1000) if started else None
    task_name = getattr(task, "name", "unknown")
    logger.info(
        "task.end task_id=%s task_name=%s state=%s duration_ms=%s",
        task_id,
        task_name,
        state,
        duration_ms,
        extra={
            "task_id": task_id,
            "task_name": task_name,
            "state": state,
            "duration_ms": duration_ms,
        },
    )
    # Keep the existing connection-cleanup behaviour.
    close_old_connections()


@task_retry.connect
def _on_task_retry(
    request: Any,
    reason: Any = None,
    *_args: Any,
    **_kwargs: Any,
) -> None:
    task_id = getattr(request, "id", None)
    task_name = getattr(request, "task", "unknown")
    retries = getattr(request, "retries", 0)
    reason_str = str(reason) if reason is not None else None
    logger.warning(
        "task.retry task_id=%s task_name=%s retries=%s reason=%s",
        task_id,
        task_name,
        retries,
        reason_str,
        extra={
            "task_id": task_id,
            "task_name": task_name,
            "retries": retries,
            "reason": reason_str,
        },
    )


@task_failure.connect
def _on_task_failure(
    task_id: str,
    exception: BaseException | None = None,
    einfo: Any = None,
    *_args: Any,
    **_kwargs: Any,
) -> None:
    # postrun fires before failure for the same task_id and pops the start
    # time, so by the time we get here `started` is normally None — that's
    # fine, the duration is already in the postrun line. The failure line
    # carries the error type + message, which postrun doesn't.
    started = _task_start_times.pop(task_id, None)
    duration_ms = round((time.perf_counter() - started) * 1000) if started else None
    error_type = type(exception).__name__ if exception else "Unknown"
    error_msg = str(exception) if exception else ""
    logger.error(
        "task.fail task_id=%s error_type=%s error=%s duration_ms=%s",
        task_id,
        error_type,
        error_msg,
        duration_ms,
        extra={
            "task_id": task_id,
            "duration_ms": duration_ms,
            "error_type": error_type,
            "error": error_msg,
        },
        exc_info=einfo,
    )
