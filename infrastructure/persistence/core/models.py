from __future__ import annotations

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
