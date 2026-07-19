"""
Shared Celery task bases and helpers.

This project already configures a global default task base in `infrastructure.celery`
(`DatabaseSafeTask`) to auto-retry transient database errors. That is a safe
baseline for all tasks because these errors are typically caused by temporary
connection churn in long-lived worker processes.

For tasks that call flaky external services, retries are *opt-in* because
automatic retries can amplify side effects unless a task is designed to be
idempotent (e.g., uses an outbox table, provider idempotency keys, or
deduplication guards).
"""

from __future__ import annotations

from celery import shared_task

from infrastructure.celery.database_safe_task import DatabaseSafeTask


def _external_autoretry_for() -> tuple[type[BaseException], ...]:
    """Return a conservative exception tuple for transient I/O failures."""
    candidates: list[type[BaseException]] = list(getattr(DatabaseSafeTask, "autoretry_for", ()))
    candidates.extend([ConnectionError, TimeoutError])

    try:  # requests is a required dependency, but keep import defensive for tests/tools.
        from requests.exceptions import RequestException
    except Exception:  # pragma: no cover
        RequestException = None
    if RequestException is not None:
        candidates.append(RequestException)

    try:  # httpx is a required dependency, but keep import defensive for tests/tools.
        import httpx
    except Exception:  # pragma: no cover
        httpx = None
    if httpx is not None:
        candidates.append(httpx.RequestError)

    # Deduplicate while preserving insertion order.
    return tuple(dict.fromkeys(candidates))


class ExternalServiceRetryTask(DatabaseSafeTask):
    """
    Retry policy for *idempotent* tasks that call external services.

    CONSTRAINTS:
    - Only use this base for tasks that are safe to run more than once.
    - Retries cover transient DB errors (via `DatabaseSafeTask`) plus common
      HTTP client/network failures (requests/httpx, timeouts, connection errors).

    DOES NOT HANDLE:
    - Ensuring idempotency or deduplicating side effects.
    - Deciding which failures are business-logic vs transient; override
      `autoretry_for`/`dont_autoretry_for` per task when needed.
    """

    autoretry_for = _external_autoretry_for()
    retry_backoff = 5
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 5


def shared_task_with_external_retry(*args, **kwargs):
    """
    Wrap `celery.shared_task` with a standard external-retry policy.

    This is intentionally strict about `name=` so routing, monitoring, and beat
    schedules remain stable across refactors.
    """
    if "name" not in kwargs:
        raise ValueError("shared_task_with_external_retry requires an explicit name= value.")
    kwargs.setdefault("base", ExternalServiceRetryTask)
    return shared_task(*args, **kwargs)

