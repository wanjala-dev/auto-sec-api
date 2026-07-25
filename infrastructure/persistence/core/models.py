from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class FeatureFlag(models.Model):
    """
    Feature flag definition.

    CONSTRAINTS:
    - `key` is a stable identifier and must never be renamed once shipped.
    - `default_enabled` should generally be False to ship features dark.
    """

    key = models.CharField(max_length=150, unique=True, db_index=True)
    default_enabled = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    @staticmethod
    def normalize_key(key: str | None) -> str:
        return (key or "").strip().lower()

    def __str__(self) -> str:
        return self.key

    def save(self, *args, **kwargs):
        """
        Enforce stable, normalized flag keys.

        Keys are immutable once created (except for normalization). This prevents
        accidental "renames" that would silently break deployed code paths.
        """
        normalized = self.normalize_key(self.key)
        if not normalized:
            raise ValidationError({"key": "Feature flag key cannot be blank."})

        if self.pk:
            existing_key = type(self).objects.filter(pk=self.pk).values_list("key", flat=True).first()
            if existing_key is not None and self.normalize_key(existing_key) != normalized:
                raise ValidationError({"key": "Feature flag keys are immutable once created."})

        self.key = normalized
        return super().save(*args, **kwargs)


class FeatureFlagRule(models.Model):
    """
    Override for a feature flag at a particular scope.

    Resolution order:
      user -> workspace -> global -> FeatureFlag.default_enabled

    Scheduling:
    - If starts_at is set, the rule is ignored until that time.
    - If ends_at is set, the rule is ignored after that time.
    """

    class Scope(models.TextChoices):
        GLOBAL = "global", "Global"
        WORKSPACE = "workspace", "Workspace"
        USER = "user", "User"

    flag = models.ForeignKey(
        FeatureFlag,
        related_name="rules",
        on_delete=models.CASCADE,
    )
    scope = models.CharField(max_length=20, choices=Scope.choices)
    enabled = models.BooleanField(default=False)

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        related_name="feature_flag_rules",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="feature_flag_rules",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_feature_flag_rules",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("flag__key", "scope", "-updated_at")
        constraints = [
            models.UniqueConstraint(
                fields=["flag", "scope"],
                condition=models.Q(scope="global"),
                name="uniq_feature_flag_global_rule",
            ),
            models.UniqueConstraint(
                fields=["flag", "scope", "workspace"],
                condition=models.Q(scope="workspace"),
                name="uniq_feature_flag_workspace_rule",
            ),
            models.UniqueConstraint(
                fields=["flag", "scope", "user"],
                condition=models.Q(scope="user"),
                name="uniq_feature_flag_user_rule",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope="global", workspace__isnull=True, user__isnull=True)
                    | models.Q(scope="workspace", workspace__isnull=False, user__isnull=True)
                    | models.Q(scope="user", workspace__isnull=True, user__isnull=False)
                ),
                name="feature_flag_rule_scope_requires_target",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.flag.key}:{self.scope}={self.enabled}"

    def is_active_now(self, now=None) -> bool:
        now = now or timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True


class DemoAccount(models.Model):
    """
    Registry of provisioned demo accounts so they can be tracked, TTL-expired,
    and torn down.

    Cleanup queries filter ``status="active"`` AND ``expires_at < now``. The
    account password is never stored here — provisioning hands it to the
    operator out-of-band.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TORN_DOWN = "torn_down", "Torn down"

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        related_name="demo_accounts",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        "users.CustomUser",
        related_name="demo_accounts",
        on_delete=models.CASCADE,
    )
    persona = models.CharField(max_length=32)
    org_slug = models.CharField(max_length=64, blank=True, default="")
    label = models.CharField(max_length=200, blank=True, default="")
    stripe_account_id = models.CharField(max_length=64, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    provisioned_by = models.CharField(max_length=120, blank=True, default="")
    # Canonical demos (e.g. the Zaylan marketing workspace that holds real
    # Stripe-test data + c0d3henry's membership) are NEVER swept or torn down,
    # regardless of expires_at — a structural guard on top of the null-expiry
    # convention so a misconfigured row can't nuke a load-bearing workspace.
    is_canonical = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "expires_at"]),
        ]

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < timezone.now()

    def __str__(self) -> str:
        return f"DemoAccount({self.persona} workspace={self.workspace_id} status={self.status})"


class BackgroundJob(models.Model):
    """A user-visible, long-running async operation with live progress.

    The canonical store for ANY long task we want to surface to a user — CSPM
    scans today, OSINT / recon / enumeration runs and report generation next.
    One row per run. Tasks drive it through the ``job_progress`` reporter
    (``components/shared_platform/infrastructure/services/job_progress.py``),
    which persists lifecycle + progress HERE and pushes a realtime event over
    the shared resource stream under a single ``resource_type`` (``RESOURCE_TYPE``
    below), so ONE generic frontend renders every job type with no per-feature
    UI work. Domain result models (e.g. ``CloudPostureScan``) stay separate —
    this only tracks the run's lifecycle + progress.
    """

    # Every job publishes under this one realtime resource_type; the concrete
    # kind of work is the ``job_type`` field. One socket subscription, N jobs.
    RESOURCE_TYPE = "background_job"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        related_name="background_jobs",
        on_delete=models.CASCADE,
    )

    job_type = models.CharField(max_length=64)  # "cloud_posture_scan", "osint_recon", ...
    # Optional soft link to the domain object this run produced (scan id, report id).
    resource_id = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    phase = models.CharField(max_length=64, blank=True, default="")
    detail = models.CharField(max_length=255, blank=True, default="")

    progress = models.PositiveSmallIntegerField(default=0)  # 0–100
    total = models.PositiveIntegerField(null=True, blank=True)  # optional denominator (e.g. checks)
    completed = models.PositiveIntegerField(default=0)  # optional numerator

    error = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workspace", "status", "-created_at"], name="bgjob_ws_status_idx"),
            models.Index(fields=["workspace", "job_type", "-created_at"], name="bgjob_ws_type_idx"),
        ]

    @property
    def is_terminal(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.FAILED, self.Status.CANCELLED}

    def __str__(self) -> str:
        return f"BackgroundJob<{self.job_type} {self.status} {self.progress}%>"
