"""The tenant binder for Celery Beat — one place, not 28.

THE BUG THIS CLOSES. Beat dispatches with no request, no host and no tenant, so
every scheduled task arrived unbound and the fail-closed router refused its first
query. Verified on the live cluster 2026-08-19 (``DATABASE_ROUTERS`` registered,
four aliases, an unbound query raising ``UnboundTenantError``): **27 of 28
scheduled tasks were affected**, including ``workflow.run_due_schedules``, which
fires every minute in every environment.

THE SHAPE OF THE FIX. Binding could have been added to 28 task bodies. It was
not, for the reason ``tenancy/management.py`` already gives about the 99
management commands: *"editing 99 files is how you get 97 done."* Beat gets one
binder at its own boundary, and a task written next year is covered the day it is
scheduled.

So a beat entry no longer names its task directly::

    "schedule_cloud_posture_scans": {
        "task": "shared_platform.run_for_each_tenant",
        "kwargs": {"task": "cloud_posture.schedule_prowler_runs"},
        "schedule": crontab(hour=2, minute=0),
    },

This task then re-dispatches the target ONCE PER TENANT with that tenant bound at
publish time, so ``before_task_publish`` stamps the tenancy headers and
``task_prerun`` binds them in the worker — the existing, proven mechanism in
``infrastructure/celery/tenancy_signals.py``. **The 28 task bodies are unchanged.**

AND IT FIXES A SECOND, QUIETER BUG. Simply binding each sweep to the pooled
console would have stopped the crash while leaving dedicated-tier tenants
unswept — their sessions never expired, their workflows never run, their cloud
accounts never scanned — with every log line reading "completed". Fanning out
means a scheduled sweep visits every tenant, and reports how many.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

#: Run the target once per tenant scope (the default, and what almost everything
#: wants): pooled console first, then every active dedicated tenant.
MODE_PER_TENANT = "per_tenant"
#: Run the target exactly ONCE, bound to the pooled console. For work over
#: GLOBAL REFERENCE DATA that is identical for every customer and routes to
#: ``default`` regardless of who is bound — the ``vuln_intel`` feeds (EPSS, CISA
#: KEV) are the load-bearing example: ~280k rows, the same for everyone, so
#: fanning them out would re-download and rewrite the identical snapshot once
#: per tenant and grow linearly with the customer count. Still BOUND, not
#: unbound, so the task's downstream domain events carry a tenancy header
#: instead of crashing one hop later.
MODE_SHARED = "shared"


@shared_task(name="shared_platform.run_for_each_tenant", soft_time_limit=120, time_limit=180)
def run_for_each_tenant(task: str, mode: str = MODE_PER_TENANT, kwargs: dict | None = None) -> dict[str, Any]:
    """Dispatch ``task`` once per tenant scope, with that tenant bound.

    ``task`` is the registered Celery name of the target — deliberately the key
    ``task`` so the beat-registration fitness test's ``"task": "..."`` scan finds
    the inner name too, and a typo in a fanned-out target still fails the build
    rather than silently never running.

    One tenant's failure never stops the rest: each dispatch is contained, logged
    with its scope, counted, and the sweep continues. The return is the
    operator-facing summary — ``dispatched`` should equal ``scopes``, and any gap
    is a tenant that did not get its sweep.
    """
    from celery import current_app

    from components.shared_platform.application.providers.tenancy_scopes_provider import (
        scheduled_sweep_scopes,
    )

    target = current_app.tasks.get(task)
    if target is None:
        # Loud and terminal: a scheduled sweep that names a task nobody
        # registered would otherwise be a silently-dead beat entry, which is the
        # exact failure class test_celery_beat_registration.py exists to prevent.
        logger.error(
            "run_for_each_tenant unknown_task=%s — the beat entry names a task that is not "
            "registered; import its module in api/celery.py or fix the name",
            task,
        )
        return {"success": False, "error": "unknown_task", "task": task, "scopes": 0, "dispatched": 0}

    scopes = scheduled_sweep_scopes()
    if mode == MODE_SHARED:
        scopes = [scope for scope in scopes if scope.is_pooled]

    dispatched = 0
    failed = 0
    for scope in scopes:
        try:
            with scope.bind():
                # Published INSIDE the binding so before_task_publish stamps the
                # tenancy headers onto the message; task_prerun then binds them
                # in the worker before the body runs.
                target.apply_async(kwargs=dict(kwargs or {}))
        except Exception:
            failed += 1
            logger.exception(
                "run_for_each_tenant dispatch_failed task=%s tenant=%s db_alias=%s",
                task,
                scope.label,
                scope.db_alias,
            )
            continue
        dispatched += 1

    logger.info(
        "run_for_each_tenant task=%s mode=%s scopes=%d dispatched=%d failed=%d",
        task,
        mode,
        len(scopes),
        dispatched,
        failed,
    )
    return {
        "success": failed == 0,
        "task": task,
        "mode": mode,
        "scopes": len(scopes),
        "dispatched": dispatched,
        "failed": failed,
    }
