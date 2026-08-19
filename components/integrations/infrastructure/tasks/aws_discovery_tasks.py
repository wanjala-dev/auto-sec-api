"""Scheduled re-discovery of AWS Organization member accounts (task #155).

THE GAP THIS CLOSES. ``organizations:ListAccounts`` ran on manual verify only.
The CloudFormation StackSet we hand the customer has ``AutoDeployment`` enabled,
so when a new account joins their Organization the audit role lands in it
correctly — and we never looked again. No ``AwsAccountLink`` row, so the scan
fan-out never saw it, so it was never scanned, while the connection kept reading
CONNECTED in the HUD. Silent coverage loss: the failure mode a security product
can least afford, because the customer's belief and the product's behaviour
diverge with nothing anywhere saying so.

Thin primary adapter, per the layer rules: it binds a tenant, calls the
application service, logs the summary. All orchestration lives in
``AwsConnectionService.rediscover_all_connections``; all ORM access lives in the
repository.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    # NO queue= pin: this rides the project default queue ("default"), which the
    # celery-worker Deployment consumes, exactly like every other per-tenant beat
    # reconciler (identity.sweep_user_sessions, remediation.*,
    # workflow.run_due_schedules, cloud_posture.schedule_prowler_runs) — none of
    # which pin a queue either.
    #
    # It SHIPPED pinned to queue="celery" and every run black-holed. That string
    # is Celery's STOCK default queue name, so it reads like "the default queue"
    # — but this project overrides task_default_queue to "default"
    # (infrastructure/celery/routes.py), so "celery" is a queue no deployed
    # worker subscribes to. Beat published it hourly into the broker for weeks
    # and nothing consumed it, while the connections it exists to reconcile kept
    # reading CONNECTED. Do not re-pin without a worker that consumes the pin;
    # tests/test_celery_task_routes.py asserts it both ways.
    name="integrations.rediscover_aws_org_accounts",
    soft_time_limit=540,
    time_limit=600,
)
def rediscover_aws_org_accounts() -> dict[str, Any]:
    """Beat entry: re-walk every CONNECTED org-wide connection and reconcile.

    Runs under the tenant the FAN-OUT bound (``shared_platform.run_for_each_tenant``
    dispatches this once per tenant scope with that tenant stamped on the
    message). It deliberately binds nothing itself: a ``pooled_scope()`` here —
    which is what this task shipped with, before the beat boundary had a binder —
    would override the fan-out's binding and pin the sweep to the pooled console
    forever, so no dedicated-tier customer's AWS org would ever be re-discovered.
    Binding belongs at the entry point, once; see
    ``components/shared_platform/infrastructure/tasks/tenancy_fanout_tasks.py``.
    """
    from components.integrations.application.providers.aws_connection_provider import (
        get_aws_connection_service,
    )

    totals = get_aws_connection_service().rediscover_all_connections()

    logger.info(
        "rediscover_aws_org_accounts connections=%d failed=%d created=%d reactivated=%d suspended=%d protected=%d",
        totals["connections"],
        totals["failed"],
        totals["created"],
        totals["reactivated"],
        totals["suspended"],
        totals["protected"],
    )
    return {"success": True, **totals}
