"""Precomputed AI usage counters per workspace.

One row per workspace holds the running daily-message + monthly-token
counters that gate ``/ai/chat/agent-chat/``. Increments happen inline
after each successful chat call (single-row ``F()`` update). Window
rollovers happen via Celery beat (``reset_daily_ai_usage_windows``,
``reset_monthly_ai_usage_windows``) — never inline on the request path.

This follows ``/architecture`` skill §6a: heavy aggregations run in the
background; the API view is a thin indexed read. The "aggregation" here
is monotonic (we only increment + reset), so there is no recompute task
— the increments themselves are the recompute. Reads are O(1).
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def _today_utc():
    """Return the current UTC date.

    Pulled out so tests can monkeypatch it without touching
    ``timezone.now``.
    """
    return timezone.now().date()


def _first_of_month_utc():
    """Return the first day of the current UTC month."""
    return _today_utc().replace(day=1)


class WorkspaceAIUsage(models.Model):
    """Running AI usage counters for one workspace.

    The counters live in two windows:

    - **Daily**: messages sent today. ``daily_window_start`` is the date
      the counter belongs to; if it's not today, the counter is stale
      and the read path returns 0 (the reset task will roll it forward
      on its next pass).
    - **Monthly**: tokens used this calendar month.
      ``monthly_window_start`` is the first day of the relevant month.

    Both counters are incremented atomically via ``F()`` after a
    successful chat call. Window rollover is centralised in
    ``reset_daily_ai_usage_windows`` / ``reset_monthly_ai_usage_windows``
    Celery beat tasks so the increment path never has to check
    "is this still today?" on every write.
    """

    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_usage",
        db_index=True,
    )

    # ── Daily messages window ────────────────────────────────────────
    daily_messages_sent = models.PositiveIntegerField(default=0)
    daily_window_start = models.DateField(
        default=_today_utc,
        db_index=True,
        help_text=_(
            "Date this daily-messages counter belongs to. If older "
            "than today, the counter is stale and reads should return 0 "
            "until the daily reset task rolls it forward."
        ),
    )

    # ── Monthly tokens window ────────────────────────────────────────
    monthly_tokens_used = models.PositiveBigIntegerField(default=0)
    monthly_window_start = models.DateField(
        default=_first_of_month_utc,
        db_index=True,
        help_text=_(
            "First day of the calendar month this monthly-tokens "
            "counter belongs to. If from a prior month, the counter is "
            "stale and reads should return 0 until the monthly reset "
            "task rolls it forward."
        ),
    )

    # Metered-AI runs (execute + deep_run) this calendar month. Its OWN
    # monthly window (decoupled from tokens so neither dimension can make the
    # other read stale across a month rollover). The cap is tier-driven via
    # the MAX_AI_RUNS_PER_MONTH entitlement — a monetization lever, distinct
    # from the cost-guardrail token/message budgets. Chat is NOT counted here.
    monthly_runs_used = models.PositiveIntegerField(default=0)
    monthly_runs_window_start = models.DateField(
        default=_first_of_month_utc,
        db_index=True,
        help_text=_(
            "First day of the calendar month this monthly-runs counter "
            "belongs to. If from a prior month, the counter is stale and "
            "reads return 0 until the monthly reset task rolls it forward."
        ),
    )

    last_message_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["daily_window_start"]),
            models.Index(fields=["monthly_window_start"]),
        ]

    def __str__(self):
        return f"{self.workspace_id} · daily={self.daily_messages_sent} · monthly_tokens={self.monthly_tokens_used}"


class AIModelDailyMetric(models.Model):
    """Per-workspace, per-model, per-day rollup of LLM-call telemetry.

    Recomputed (not incremented) by the ``ai.rollup_ai_quality_daily``
    Celery beat task from raw ``DeepRunLog`` llm-call rows, so re-runs
    are idempotent and late-arriving rows converge on the next pass.
    The analytics endpoint reads ONLY these rollup rows — never the raw
    log — per the performance rule that heavy aggregation runs in the
    background and API reads stay indexed and O(window).

    Percentiles are stored (not raw latencies) because a day×model
    bucket is the finest granularity the dashboard renders.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_model_daily_metrics",
    )
    date = models.DateField()
    model_used = models.CharField(max_length=100)

    llm_calls = models.PositiveIntegerField(default=0)
    prompt_tokens = models.PositiveBigIntegerField(default=0)
    completion_tokens = models.PositiveBigIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    latency_p50_ms = models.PositiveIntegerField(null=True, blank=True)
    latency_p95_ms = models.PositiveIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "date", "model_used"],
                name="uniq_ws_date_model_metric",
            ),
        ]
        indexes = [
            # The dashboard window query: workspace + date range.
            models.Index(fields=["workspace", "-date"], name="ai_model_metric_ws_date_idx"),
        ]
        ordering = ["-date", "model_used"]

    def __str__(self):
        return f"{self.workspace_id} · {self.date} · {self.model_used} · calls={self.llm_calls}"


class AIWorkspaceDailyMetric(models.Model):
    """Per-workspace, per-day rollup of run outcomes + user feedback.

    Kept separate from :class:`AIModelDailyMetric` because feedback
    attaches to conversation messages, not to a specific model — the
    two series have different natural keys. Same recompute-not-increment
    contract, same beat task.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_workspace_daily_metrics",
    )
    date = models.DateField()

    runs_total = models.PositiveIntegerField(default=0)
    runs_completed = models.PositiveIntegerField(default=0)
    runs_failed = models.PositiveIntegerField(default=0)
    assistant_messages = models.PositiveIntegerField(default=0)
    feedback_up = models.PositiveIntegerField(default=0)
    feedback_down = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "date"],
                name="uniq_ws_date_workspace_metric",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "-date"], name="ai_ws_metric_ws_date_idx"),
        ]
        ordering = ["-date"]

    def __str__(self):
        return (
            f"{self.workspace_id} · {self.date} · runs={self.runs_total}"
            f" · up={self.feedback_up} · down={self.feedback_down}"
        )


class AIModelChangeEvent(models.Model):
    """One record per workspace AI model switch — dashboard annotations.

    Written by ``OrmWorkspaceAIConfigAdapter.save`` whenever the stored
    ``preferred_model`` / ``fallback_model`` actually changes, so charts
    can render "model switched here" vertical markers over the metric
    series (the Grafana deploy-annotation pattern). Append-only.
    """

    FIELD_PREFERRED = "preferred_model"
    FIELD_FALLBACK = "fallback_model"
    FIELD_CHOICES = [
        (FIELD_PREFERRED, "Preferred model"),
        (FIELD_FALLBACK, "Fallback model"),
    ]

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_model_change_events",
    )
    changed_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_model_change_events",
    )
    field = models.CharField(max_length=32, choices=FIELD_CHOICES)
    old_value = models.CharField(max_length=100, blank=True, default="")
    new_value = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="ai_model_change_ws_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.workspace_id} · {self.field}: {self.old_value} → {self.new_value}"


class IndexFreshnessSample(models.Model):
    """One measurement of how stale a workspace's pgvector snapshot is.

    The Tier 3 #14 index-freshness SLO is "95% of active workspaces
    have lag ≤ 600 seconds." Lag is defined as:

        max(0, latest_workspace_event_time - latest_index_time)

    where ``latest_workspace_event_time`` is the most recent of any
    domain edit that should have triggered a reindex (Workspace,
    Donation, Recipient, Campaign, Grant, Project, Team,
    WorkspaceMembership) and ``latest_index_time`` is the most recent
    ``EmbeddingChunk.created_at`` for the workspace.

    The Celery beat ``audit_index_freshness`` task writes one row per
    workspace per measurement pass. The samples are append-only and
    indexed by ``(sample_time, workspace_id)`` so trend queries
    ("p95 lag over last 7 days for workspace X") + the global SLO
    compliance query stay cheap.

    No retention policy here on purpose — the rows are small
    (~80 bytes each, ~1 MB per 12k samples) and operators may want
    a long window of history when investigating a freshness
    regression. If volume ever becomes a concern, add a beat task
    that prunes rows older than a configurable threshold.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="index_freshness_samples",
    )

    sample_time = models.DateTimeField(
        default=timezone.now,
        help_text=_("When this measurement was taken. Always in UTC."),
    )

    latest_event_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Most recent timestamp across the watched domain models. "
            "NULL means the workspace has no events at all — treated "
            "as fresh by the SLO (lag = 0)."
        ),
    )

    latest_index_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Most recent EmbeddingChunk.created_at for this workspace. NULL means the workspace has never been indexed."
        ),
    )

    lag_seconds = models.PositiveIntegerField(
        help_text=_(
            "max(0, latest_event_time - latest_index_time). Clamped to "
            "0 when the index is newer than the event (the workspace "
            "is fully fresh)."
        ),
    )

    sla_target_seconds = models.PositiveIntegerField(
        help_text=_(
            "The SLO target lag at measurement time. Recorded per row "
            "so an SLO retune doesn't retroactively re-categorise "
            "historical samples."
        ),
    )

    sla_met = models.BooleanField(
        help_text=_(
            "True iff lag_seconds <= sla_target_seconds. Computed at "
            "write time so the global compliance query is a fast "
            "aggregate without recomputing per row."
        ),
    )

    class Meta:
        indexes = [
            # Trend query: "p95 lag for this workspace over the last
            # 7 days." (workspace, sample_time DESC) covers it.
            models.Index(fields=["workspace", "-sample_time"]),
            # Global compliance query: "what fraction of samples in
            # the last hour met SLA?" (-sample_time, sla_met).
            models.Index(fields=["-sample_time", "sla_met"]),
        ]
        ordering = ["-sample_time", "workspace_id"]

    def __str__(self):
        return (
            f"{self.workspace_id} · {self.sample_time:%Y-%m-%d %H:%M} · "
            f"lag={self.lag_seconds}s · sla_met={self.sla_met}"
        )
