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
    name="integrations.rediscover_aws_org_accounts",
    queue="celery",
    soft_time_limit=540,
    time_limit=600,
)
def rediscover_aws_org_accounts() -> dict[str, Any]:
    """Beat entry: re-walk every CONNECTED org-wide connection and reconcile.

    Binds the pooled console explicitly. A beat-dispatched task arrives with no
    tenant stamped on it (beat has no request and no host), and the fail-closed
    router refuses unbound queries — "leave it alone" on a long-lived prefork
    child means inheriting whatever the previous task bound, which is a
    cross-tenant read waiting to happen (tenancy skill §3b/§3i).
    """
    from components.integrations.application.providers.aws_connection_provider import (
        get_aws_connection_service,
    )
    from components.shared_platform.application.providers.tenancy_scopes_provider import (
        pooled_scope,
    )

    with pooled_scope():
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
