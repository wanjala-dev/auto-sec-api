"""Seed core feature flags and optional user-level overrides.

Idempotent — safe to run multiple times. Creates flags if missing,
skips if they already exist.

When DEBUG is False (production), also ensures global rules exist that
disable flags listed in PROD_DISABLED_FLAGS — this hides those features
from the UI in prod while keeping them enabled by default in dev/local.

Usage:
    # Seed all default flags
    python manage.py seed_feature_flags

    # Also enable dev_tools for a specific user (by email)
    python manage.py seed_feature_flags --dev-tools-user=admin@test.octopi.dev
"""

from __future__ import annotations

from django.conf import settings
from django.core.management import BaseCommand

from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.users.models import CustomUser

# Flags to seed: (key, default_enabled, description)
DEFAULT_FLAGS = [
    (
        "feature.ai_kill_switch",
        False,
        "Emergency kill switch. Default off. An operator trips it "
        "(global FeatureFlagRule to halt all AI, or workspace-scoped for one) to "
        "stop AI execution — chat, deep runs, and the autonomous detector — "
        "without a deploy. Not a product toggle (that is per-workspace "
        "ai_enabled); this is operator break-glass.",
    ),
    (
        "dev_tools",
        False,
        "Enable developer tools (persona switcher, debug panels) for specific users in production.",
    ),
    (
        "feature.support_impersonation",
        False,
        "Allow the user to start a SupportImpersonationSession granting them the "
        "chosen persona/role on a target workspace for 30 minutes. Per-user enable "
        "rule expected; never globally enabled.",
    ),
    (
        "feature.provenance_graph",
        False,
        "Provenance & access graph (who — human / service account / AI agent / "
        "vendor — can touch what, and what they actually touched). Off in prod "
        "until GA; per-workspace opt-in. Read-only observation, never mutates a "
        "vendor's permissions. See docs/plans/PROVENANCE_ACCESS_GRAPH_2026-07-17.md.",
    ),
]


# Flags that should be globally disabled in production (DEBUG=False).
# Dev/local (DEBUG=True) leaves them at their default_enabled value.
# Add product feature-gate keys here as they are introduced.
PROD_DISABLED_FLAGS = ("feature.provenance_graph",)


# Flags that, while globally disabled in production, are kept enabled for a
# small allow-list of operator accounts via USER-scoped rules. Used for
# features that are not yet GTM-ready, where the operator needs live access
# in prod ahead of general availability. Map ``flag_key -> (emails, ...)``.
PROD_ALLOWLISTED_USER_FLAGS = {}


class Command(BaseCommand):
    help = "Seed core feature flags and optional user-level overrides."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dev-tools-user",
            type=str,
            help="Email of the user to enable dev_tools for (creates a user-level rule).",
        )
        parser.add_argument(
            "--enable-flag-for-user",
            type=str,
            nargs=2,
            metavar=("FLAG_KEY", "EMAIL"),
            action="append",
            default=[],
            help=(
                "Generic per-user flag enable. Pass multiple times for multiple "
                "flags. Example: --enable-flag-for-user "
                "feature.support_impersonation henry@example.com"
            ),
        )

    def handle(self, *args, **options):
        self._seed_flags()
        self._apply_environment_rules()
        self._apply_prod_allowlist_rules()
        dev_tools_email = options.get("dev_tools_user")
        if dev_tools_email:
            self._enable_flag_for_user("dev_tools", dev_tools_email)
        for pair in options.get("enable_flag_for_user", []) or []:
            flag_key, email = pair
            self._enable_flag_for_user(flag_key, email)

    def _seed_flags(self):
        for key, default_enabled, description in DEFAULT_FLAGS:
            flag, created = FeatureFlag.objects.get_or_create(
                key=key,
                defaults={
                    "default_enabled": default_enabled,
                    "description": description,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  Created flag: {key} (default={default_enabled})"))
            else:
                self.stdout.write(f"  Flag already exists: {key}")

    def _apply_environment_rules(self):
        """Ensure prod has global disable rules; dev/local clears them."""
        is_prod = not settings.DEBUG
        for key in PROD_DISABLED_FLAGS:
            flag = FeatureFlag.objects.filter(key=key).first()
            if not flag:
                continue
            if is_prod:
                rule, created = FeatureFlagRule.objects.update_or_create(
                    flag=flag,
                    scope=FeatureFlagRule.Scope.GLOBAL,
                    defaults={
                        "enabled": False,
                        "note": "Disabled in production by seed_feature_flags.",
                    },
                )
                action = "Created" if created else "Updated"
                self.stdout.write(self.style.SUCCESS(f"  {action} global disable rule: {key}"))
            else:
                deleted, _ = FeatureFlagRule.objects.filter(
                    flag=flag,
                    scope=FeatureFlagRule.Scope.GLOBAL,
                    note="Disabled in production by seed_feature_flags.",
                ).delete()
                if deleted:
                    self.stdout.write(f"  Removed prod disable rule: {key}")

    def _apply_prod_allowlist_rules(self):
        """In prod, re-enable globally-disabled flags for allow-listed operators.

        Dev/local leaves these alone — the flag is already on by default
        there (no global disable rule), so the per-user override is redundant.
        Idempotent; a missing user is logged and skipped by the helper.
        """
        if settings.DEBUG:
            return
        for flag_key, emails in PROD_ALLOWLISTED_USER_FLAGS.items():
            for email in emails:
                self._enable_flag_for_user(flag_key, email)

    def _enable_flag_for_user(self, flag_key: str, email: str):
        """Idempotently create a USER-scoped FeatureFlagRule that enables
        ``flag_key`` for the user with the given email."""
        flag = FeatureFlag.objects.filter(key=flag_key).first()
        if not flag:
            self.stderr.write(self.style.ERROR(f"  {flag_key} flag not found — run seed first."))
            return

        user = CustomUser.objects.filter(email__iexact=email).first()
        if not user:
            self.stderr.write(self.style.ERROR(f"  User not found: {email}"))
            return

        _rule, created = FeatureFlagRule.objects.get_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.USER,
            user=user,
            defaults={
                "enabled": True,
                "note": f"Per-user enable: {flag_key} for {email}",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  Enabled {flag_key} for user: {email}"))
        else:
            self.stdout.write(f"  {flag_key} rule already exists for: {email}")
