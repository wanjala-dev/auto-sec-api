"""Celery tasks for the Tier 3 #14 index-freshness SLO.

One public task:

- ``audit_index_freshness()`` — beat-scheduled. Walks every active
  workspace, measures lag via ``MeasureIndexFreshnessUseCase``,
  persists one ``IndexFreshnessSample`` per workspace, and emits a
  WARNING log line if the per-pass SLO compliance fraction drops
  below the target.

Retry policy is light because the audit is idempotent — each pass
overwrites nothing, just appends a fresh sample. A failed pass
becomes a hole in the sample stream; the next pass 10 minutes
later catches up.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# SLO target (as a fraction, 0..1). The audit task computes the
# fraction of workspaces meeting the per-row SLA at each pass and
# logs a WARNING if it drops below this floor. 0.95 = "95% of
# workspaces are within the per-row threshold." Tunable via the
# SLO doc in RAG_AUDIT_AND_ROADMAP.md — this constant is the
# single source of truth.
PASS_COMPLIANCE_TARGET = 0.95


@shared_task(
    name="components.knowledge.index_freshness.audit_index_freshness",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
    retry_backoff=True,
    soft_time_limit=300,
    time_limit=600,
)
def audit_index_freshness(self) -> dict:
    """Measure freshness for every active workspace; persist samples.

    Returns a summary dict so a manual ``.apply()`` from the Django
    shell shows the result inline.

    Failure isolation: per-workspace measurement is wrapped in
    try/except. One workspace's measurement crashing (e.g. its
    Donation table has corrupt rows) cannot stop the audit pass for
    the rest. The log line names the workspace_id so the operator
    can investigate.
    """
    from django.utils import timezone

    from components.knowledge.application.providers.index_freshness_provider import (
        measure_index_freshness,
    )
    from components.knowledge.application.use_cases.measure_index_freshness_use_case import (
        DEFAULT_SLA_TARGET_SECONDS,
    )
    from infrastructure.persistence.ai.aggregations.models import (
        IndexFreshnessSample,
    )
    from infrastructure.persistence.workspaces.models import Workspace

    use_case = measure_index_freshness()
    sample_time = timezone.now()
    sla_target_seconds = DEFAULT_SLA_TARGET_SECONDS

    # Stream workspaces with iterator(chunk_size=500) — same scaling
    # discipline as ``reindex_all_workspaces``. Tier 3 #14 audit.
    queryset = (
        Workspace.objects.filter(is_active=True)
        .order_by("id")
        .values_list("id", flat=True)
    )

    samples_to_insert: list[IndexFreshnessSample] = []
    total = 0
    sla_met_count = 0
    failed = 0

    for workspace_id in queryset.iterator(chunk_size=500):
        total += 1
        try:
            sample = use_case.execute(
                workspace_id=str(workspace_id),
                sample_time=sample_time,
                sla_target_seconds=sla_target_seconds,
            )
        except Exception:  # pylint: disable=broad-except
            failed += 1
            logger.exception(
                "knowledge: index freshness measurement failed "
                "workspace_id=%s — skipping",
                workspace_id,
            )
            continue

        if sample.sla_met:
            sla_met_count += 1
        samples_to_insert.append(
            IndexFreshnessSample(
                workspace_id=sample.workspace_id,
                sample_time=sample.sample_time,
                latest_event_time=sample.latest_event_time,
                latest_index_time=sample.latest_index_time,
                lag_seconds=sample.lag_seconds,
                sla_target_seconds=sample.sla_target_seconds,
                sla_met=sample.sla_met,
            )
        )

    if samples_to_insert:
        # bulk_create — one INSERT for the whole pass instead of N
        # round-trips. The samples are independent rows so there's
        # no FK contention.
        IndexFreshnessSample.objects.bulk_create(
            samples_to_insert, batch_size=500
        )

    compliance = sla_met_count / total if total else 1.0
    summary = {
        "sample_time": sample_time.isoformat(),
        "total_workspaces": total,
        "sla_met": sla_met_count,
        "failed_measurement": failed,
        "sla_target_seconds": sla_target_seconds,
        "compliance_fraction": round(compliance, 4),
        "pass_compliance_target": PASS_COMPLIANCE_TARGET,
        "pass_target_met": compliance >= PASS_COMPLIANCE_TARGET,
    }

    if total and compliance < PASS_COMPLIANCE_TARGET:
        logger.warning(
            "knowledge: index freshness SLO violated compliance=%.3f "
            "target=%.3f sla_met=%s/%s sla_target_seconds=%s",
            compliance,
            PASS_COMPLIANCE_TARGET,
            sla_met_count,
            total,
            sla_target_seconds,
        )
    else:
        logger.info(
            "knowledge: index freshness audit completed compliance=%.3f "
            "target=%.3f sla_met=%s/%s failed=%s",
            compliance,
            PASS_COMPLIANCE_TARGET,
            sla_met_count,
            total,
            failed,
        )

    return summary


# Days of IndexFreshnessSample history to retain. 30 days × 144
# samples / day / workspace = ~4,300 rows per workspace, ~80 bytes
# each → ~350 KB per workspace per month. Trivial at our scale;
# enough trend depth to spot weekly cycles + post-deploy regressions.
INDEX_FRESHNESS_SAMPLE_RETENTION_DAYS = 30


@shared_task(
    name="components.knowledge.index_freshness.prune_index_freshness_samples",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=300,
    time_limit=600,
)
def prune_index_freshness_samples(
    self, retention_days: int | None = None
) -> dict:
    """Delete IndexFreshnessSample rows older than retention.

    Runs daily from Celery beat (see prod.py beat schedule).
    Plain ``.filter(sample_time__lt=cutoff).delete()`` — at our
    scale (hundreds of workspaces × 144 samples/day × 30 days =
    a few hundred thousand rows) this is well under a second.

    Scaling note: when this DELETE starts exceeding ~5 seconds in
    prod (or the row count crosses ~50M), the right move is to
    migrate the table to time-based partitioning per the
    [oneuptime 2026 guide](https://oneuptime.com/blog/post/
    2026-01-26-time-based-partitioning-postgresql/view) —
    dropping monthly partitions is instant where DELETE is O(N).
    Don't pre-build that until the cost shows up.
    """
    from datetime import timedelta

    from django.utils import timezone

    from infrastructure.persistence.ai.aggregations.models import (
        IndexFreshnessSample,
    )

    days = (
        retention_days
        if retention_days is not None
        else INDEX_FRESHNESS_SAMPLE_RETENTION_DAYS
    )
    cutoff = timezone.now() - timedelta(days=days)

    deleted, _ = IndexFreshnessSample.objects.filter(
        sample_time__lt=cutoff
    ).delete()

    logger.info(
        "knowledge: pruned IndexFreshnessSample rows older than "
        "%s days cutoff=%s rows_deleted=%s",
        days,
        cutoff.isoformat(),
        deleted,
    )
    return {
        "retention_days": days,
        "cutoff": cutoff.isoformat(),
        "rows_deleted": deleted,
    }
