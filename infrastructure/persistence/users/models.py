import uuid

# Create your models here.
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from infrastructure.persistence.countries.models import Country


class UserManager(BaseUserManager):
    def make_random_password(self, length=10, allowed_chars="abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"):
        """
        Django 5 dropped BaseUserManager.make_random_password; preserve it for callers.
        """
        return get_random_string(length, allowed_chars)

    def create_user(self, username, email, password=None):
        if username is None:
            raise TypeError("Users should have a username")
        if email is None:
            raise TypeError("Users should have a Email")

        user = self.model(username=username, email=self.normalize_email(email))
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, username, email, password=None):
        if password is None:
            raise TypeError("Password should not be none")

        user = self.create_user(username, email, password)
        user.is_superuser = True
        user.is_staff = True
        user.is_admin = True
        user.save()
        return user


AUTH_PROVIDERS = {"google": "google", "email": "email"}


class CustomUser(AbstractUser):
    id = models.UUIDField(max_length=200, default=uuid.uuid4, unique=True, primary_key=True, editable=False)
    username = models.CharField(max_length=250, blank=True)
    email = models.EmailField(_("email address"), unique=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_onboard_complete = models.BooleanField(default=False)
    is_contributor = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    two_factor_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    auth_provider = models.CharField(max_length=255, blank=False, null=False, default=AUTH_PROVIDERS.get("email"))
    google_sub = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text=(
            "Stable Google account id (OIDC 'sub') used to link a social "
            "sign-in to this user. Null for non-Google accounts. Postgres "
            "permits multiple NULLs under a UNIQUE constraint, so this stays "
            "unique only across accounts that actually have a Google id."
        ),
    )
    # sectors M2M dropped in the auto-sec fork (sectors context removed).

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    # @property
    # def full_name(self):
    #     return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.id}-{self.email}"

    def tokens(self):
        # The real issuer lives in the identity component. The previous
        # import path (infrastructure.persistence.users.utils) doesn't
        # exist in this codebase and would 500 every caller. We import
        # lazily because the identity adapter pulls in DRF/JWT which we
        # don't want at model-load time.
        from components.identity.infrastructure.adapters.user_utils import (
            issue_tokens,
        )

        tokens = issue_tokens(
            self,
            otp_verified=False,
            device=None,
            include_refresh=True,
        )
        return {
            "refresh": tokens.get("refresh"),
            "access": tokens.get("access"),
        }

    # def save(self, *args, **kwargs):
    #     self.email = self.email.lower()
    #     super(User, self).save(*args, **kwargs)

    # class Meta:
    #     verbose_name_plural = "users"
    #     ordering = ["email"]
    #     indexes = [models.Index(fields=["email"])]
    def num_campaigns_posted(self):
        return self.campaign_owner.count()

    def get_related_workspaces_queryset(self):
        """Return distinct workspaces the user has any relationship to.

        Unions four relationship sources:
          * owner — workspace_owner
          * team member — via Team.members M2M
          * workspace member — via WorkspaceMembership
          * follower — via Workspace.followers M2M

        (The donor branch — Transaction.user with transaction_type='donation'
        — was dropped in the auto-sec fork along with the
        sponsorship/transactions context.)
        """
        from infrastructure.persistence.workspaces.models import (
            Workspace,
        )  # Local import to avoid circular dependency

        return Workspace.objects.filter(
            Q(workspace_owner=self) | Q(workspace_teams__members=self) | Q(memberships__user=self) | Q(followers=self)
        ).distinct()


class UserProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="profile")
    active_team_id = models.IntegerField(default=0)
    active_workspace_id = models.UUIDField(null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    dob = models.DateField(auto_now=False, null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    about = models.TextField(null=True, blank=True)
    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True)
    zip = models.CharField(max_length=5, blank=True, null=True)
    photo_url = models.CharField(max_length=500, blank=True, null=True)
    banner_photo_url = models.CharField(max_length=500, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=30, blank=True, null=True)
    followers = models.ManyToManyField(CustomUser, blank=True, related_name="followers")

    def get_followers_count(self):
        return self.followers.count()

    def get_following_count(self):
        return self.user.followers.count()

    def __str__(self):
        return f"{self.user.id}-{self.user.email}"


class InvitedUser(models.Model):
    email = models.EmailField(_("email address"), unique=True)
    invitation_code = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class MagicLinkToken(models.Model):
    """Single-use passwordless sign-in token.

    Powers the post-donation "track this gift" CTA: a donor who gave
    anonymously-but-with-email through the public donate flow can
    request a one-click sign-in link that drops them straight into
    ``/donations/mine`` with their gifts already attributed by email
    match.

    Security model
    --------------
    - ``token`` is 256 bits of URL-safe random data (``secrets.token_urlsafe(32)``);
      hash storage is a follow-up hardening pass.
    - ``expires_at`` defaults to 15 min after creation; the verify view
      rejects expired rows up-front.
    - ``consumed_at`` makes the token strictly single-use. Replay
      protection: even within the 15-minute window, the second click
      hits ``consumed_at IS NOT NULL`` and 400s.
    - The request view is throttled (``MagicLinkRequestThrottle``,
      5/hour per email+IP) so an attacker can't enumerate accounts by
      flooding the endpoint and watching SES bounce rates.

    Field notes
    -----------
    - ``email`` is stored as the user typed it; the verify path looks
      up the user by case-insensitive match so "Alice@example.com"
      and "alice@example.com" land on the same account.
    - ``next_url`` lets the request endpoint preserve a deep link
      across the email round-trip — e.g. send the donor back to
      ``/donations/mine`` after sign-in. Validated against an
      allow-list at verify time so it can't be turned into an
      open-redirect vector.
    - ``user`` FK is intentionally nullable. The donor's email may
      not match any existing account at request time; the verify path
      creates the account on first click and back-links the token.
    """

    token = models.CharField(max_length=255, unique=True, db_index=True)
    email = models.EmailField(db_index=True)
    user = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="magic_links",
    )
    next_url = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["email", "-created_at"], name="mlink_email_created_idx"),
        ]

    def __str__(self) -> str:
        return f"MagicLinkToken<{self.email}>"


class ContributorProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="contributor_profile")
    preferred_locations = models.ManyToManyField(Country, blank=True, related_name="contributors")
    contribution_means = models.ManyToManyField("workspaces.ContributionMeans", blank=True, related_name="contributors")

    def __str__(self):
        return f"Contributor Profile for {self.user.email}"


class UserSession(models.Model):
    """One row per issued refresh token — the login-session registry.

    Invariant this model depends on: ``SIMPLE_JWT["ROTATE_REFRESH_TOKENS"]``
    is ``False`` in every settings module, so a refresh token's ``jti`` is
    STABLE for the whole lifetime of a login. That makes ``refresh_jti`` a
    durable session identifier: token refreshes only bump ``last_seen_at``
    on the same row instead of minting a new jti. If token rotation is ever
    enabled, this registry must be reworked to chain rotated jtis — do not
    flip that setting without revisiting this model.

    ``sid`` claims stamped on both access and refresh tokens at issuance
    (see ``components/identity/infrastructure/adapters/user_utils.issue_tokens``)
    carry ``refresh_jti`` so any token can be traced back to its session.

    Enrichment fields (device/browser/OS/geo) are populated asynchronously
    by a later slice (T2-S2); they stay blank at creation time.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    # FK / relations
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    # Data fields
    refresh_jti = models.CharField(max_length=64, unique=True)
    login_method = models.CharField(max_length=16)  # password|google|magic_link|otp
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    device_type = models.CharField(max_length=16, blank=True, default="")
    browser = models.CharField(max_length=64, blank=True, default="")
    browser_version = models.CharField(max_length=32, blank=True, default="")
    os = models.CharField(max_length=64, blank=True, default="")
    os_version = models.CharField(max_length=32, blank=True, default="")
    geo_city = models.CharField(max_length=128, blank=True, default="")
    geo_country = models.CharField(max_length=64, blank=True, default="")
    geo_country_code = models.CharField(max_length=2, blank=True, default="")
    enriched_at = models.DateTimeField(null=True, blank=True)
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["user", "-last_seen_at"], name="usersession_user_seen_idx"),
            models.Index(fields=["user", "revoked_at"], name="usersession_user_revoked_idx"),
        ]

    def __str__(self) -> str:
        return f"UserSession<{self.user_id}:{self.refresh_jti[:8]}>"


class AuthAuditEvent(models.Model):
    """Persistent audit trail for authentication and 2FA activity."""

    EVENT_LOGIN = "auth.login"
    EVENT_LOGIN_FAILED = "auth.login_failed"
    EVENT_OTP_VERIFY = "auth.otp_verify"
    EVENT_OTP_VERIFY_FAILED = "auth.otp_verify_failed"
    EVENT_PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
    EVENT_PASSWORD_RESET_COMPLETED = "auth.password_reset_completed"
    EVENT_EMAIL_VERIFY = "auth.email_verify"

    user = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="auth_audit_events",
    )
    session = models.ForeignKey(
        UserSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    email = models.EmailField(blank=True, default="")
    event_code = models.CharField(max_length=64)
    success = models.BooleanField(default=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_code", "created_at"], name="auth_audit_event_idx"),
            models.Index(fields=["email", "created_at"], name="auth_audit_email_idx"),
            models.Index(fields=["user", "-created_at"], name="auth_audit_user_created_idx"),
        ]


class WorkspaceLoginActivityExclusion(models.Model):
    """Per-workspace hide/exclude marker for a login-activity audit event.

    Lets a workspace admin hide a specific auth event from the workspace's
    login-activity surface without mutating the append-only audit trail.
    Model only in this slice — the API/wiring lands in T2-S4.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="login_activity_exclusions",
    )
    event = models.ForeignKey(
        AuthAuditEvent,
        on_delete=models.CASCADE,
        related_name="workspace_exclusions",
    )
    hidden_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hidden_login_activity_events",
    )
    hidden_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "event"],
                name="uniq_ws_login_activity_exclusion",
            ),
        ]


# Register legacy module aliases so imports like ``users.models`` reuse this module.
import importlib
import sys

sys.modules.setdefault("users", importlib.import_module("infrastructure.users"))
sys.modules.setdefault("users.models", sys.modules[__name__])
