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

from components.shared_platform.infrastructure.services.feature_flags import bump_feature_flags_version
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
    (
        "feature.cloud_posture",
        True,
        "Cloud posture (CSPM) — Prowler-as-engine per-account scans → posture "
        "snapshots + findings. ON by default: a scanner capability ships in Free "
        "(docs/product/PRICING_PACKAGING_RECOMMENDATION_2026-08-08.md), so this "
        "flag is a kill-switch, not an entitlement gate. Harmless while ON — no "
        "scan runs without a CONNECTED AwsOrganizationConnection (the customer's "
        "deployed audit role IS the consent), and an explicit workspace/global "
        "disable rule still wins. See docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md §3.3.",
    ),
    (
        "feature.logwatch_board_from_findings",
        False,
        "Reversible board cutover for logwatch (ADR 0004): when ON per-workspace, the "
        "detector cycle stands down its board write and the Finding SSOT path "
        "(FindingObserved → FindingRaised → finding_raised_board_handler) drives the "
        "board instead. Default OFF — the flagship log lane is only flipped once "
        "dual-write parity is observed. Mirrors the cloud_posture cutover (#98/#101).",
    ),
    (
        "feature.container_security",
        True,
        "Container security (SCA) — Trivy-as-engine image vulnerability scans "
        "(ADR 0006) run as ephemeral, gVisor-isolated Kubernetes Jobs on the "
        "ScanExecutionBackend → NormalizedFindings in the SSOT. ON by default: "
        "ships in Free (pricing rec 2026-08-08), so the flag is a kill-switch, not "
        "an entitlement gate. Harmless while ON — a scan only runs when a "
        "workspace member supplies an image target (the beat cycle has no image "
        "source yet), and an explicit disable rule still wins. See "
        "docs/adr/0006-scanner-execution-substrate.md.",
    ),
    (
        "feature.code_security",
        True,
        "Code security (SAST) — Opengrep-as-engine scans of allowlisted VCS repos "
        "(ADR 0019) run as ephemeral, hardened Kubernetes Jobs on the "
        "ScanExecutionBackend → NormalizedFindings (file/line/rule/snippet) in the "
        "SSOT + board cards at the high+critical floor. ON by default: ships in "
        "Free (pricing rec 2026-08-08), so the flag is a kill-switch, not an "
        "entitlement gate. Harmless while ON — nothing scans without a CONNECTED "
        "VcsConnection + repo allowlist (the customer's PAT IS the consent), and "
        "an explicit disable rule still wins. See "
        "docs/adr/0019-sast-code-scanning-pillar.md.",
    ),
    (
        "feature.vercel_posture",
        True,
        "Vercel posture (ADR 0021) — Prowler `vercel`-provider scans of a "
        "workspace's ONE consented Vercel team (VercelConnection, token-shaped) "
        "run as ephemeral hardened Kubernetes Jobs on the scanning spine → "
        "NormalizedFindings with urn:vercel: URNs in the SSOT + board cards at "
        "the high+critical floor. A deliberate SIBLING of feature.cloud_posture, "
        "never a reuse — AWS CSPM opt-in is not Vercel consent. ON by default: "
        "ships in Free (pricing rec 2026-08-08), so the flag is a kill-switch, "
        "not an entitlement gate. Harmless while ON — no scan runs without a "
        "CONNECTED VercelConnection (the customer's token IS the consent), and an "
        "explicit disable rule still wins. See docs/adr/0021-vercel-posture-provider.md.",
    ),
    (
        "feature.cloud_asset_graph",
        False,
        "Cloud asset graph (ADR 0004 / CNAPP): the code-to-cloud resource graph "
        "(CloudAsset + typed edges) the attack-path correlation runs over. Off until "
        "GA; per-workspace opt-in. Substrate-agnostic — Prowler-derived inventory now, "
        "CloudQuery-backfillable later with no schema change. See "
        "docs/plans/CLOUD_ASSET_GRAPH_SPIKE.md.",
    ),
    (
        "feature.log_source_cloudwatch",
        True,
        "Multi-source log ingestion (ADR 0008 D5): registers the CloudWatch Logs "
        "LogSourcePort adapter — the second real log source after S3. On by default; "
        "flip OFF to hide CloudWatch from the Log Sources API/UI. Datadog/Splunk follow "
        "the same per-adapter flag pattern. See docs/adr/0008-multi-source-log-ingestion-port.md.",
    ),
    (
        "feature.sample_data_mode",
        False,
        "Per-workspace demo/sample-data mode (ADR 0011): when ON for a workspace, the demo "
        "banner shows and the workspace holds injected, tagged sample data so a trial can "
        "explore a populated product; OFF tears it down so they set up live integrations. "
        "The owner toggles it in Settings; the flag is the demo-mode SSOT + trial→paying lever. "
        "Off by default; per-workspace opt-in.",
    ),
]


# Flags that should be globally disabled in production (DEBUG=False).
# Dev/local (DEBUG=True) leaves them at their default_enabled value.
# Add product feature-gate keys here as they are introduced.
#
# The four scanner capabilities (feature.cloud_posture, feature.container_security,
# feature.code_security, feature.vercel_posture) deliberately LEFT this list on
# 2026-08-08: they ship in Free (see the pricing recommendation), so their flags
# are kill-switches, not entitlement gates — default-ON everywhere, with the
# break-glass being an explicit GLOBAL/WORKSPACE disable rule (which the resolver
# ladder honours over the default). Stale seed-created disable rules for keys
# that leave this list are cleaned up by ``_apply_environment_rules``.
PROD_DISABLED_FLAGS = (
    "feature.provenance_graph",
    "feature.sample_data_mode",
)

# The exact note the seed stamps on its own global disable rules. Cleanup is
# matched on this note so operator-created rules (a real kill-switch) are
# never touched by the seed.
PROD_DISABLE_NOTE = "Disabled in production by seed_feature_flags."


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
        # Flag/rule writes above bypass the API layer's cache invalidation —
        # bump the version so evaluations pick the new state up immediately
        # instead of after the 300s TTL.
        bump_feature_flags_version()

    def _seed_flags(self):
        for key, default_enabled, description in DEFAULT_FLAGS:
            _flag, created = FeatureFlag.objects.get_or_create(
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
        """Ensure prod has global disable rules; remove ones no longer warranted.

        Cleanup is note-matched (``PROD_DISABLE_NOTE``) so an operator's own
        global rules — a deliberate kill-switch — are never touched. It runs in
        every environment: dev/local clears every seed-created disable, and prod
        clears only those whose key has LEFT ``PROD_DISABLED_FLAGS`` (e.g. the
        scanner capabilities that flipped default-on 2026-08-08 — without this,
        a previously-seeded prod DB would keep them dark forever).
        """
        is_prod = not settings.DEBUG
        if is_prod:
            for key in PROD_DISABLED_FLAGS:
                flag = FeatureFlag.objects.filter(key=key).first()
                if not flag:
                    continue
                _rule, created = FeatureFlagRule.objects.update_or_create(
                    flag=flag,
                    scope=FeatureFlagRule.Scope.GLOBAL,
                    defaults={
                        "enabled": False,
                        "note": PROD_DISABLE_NOTE,
                    },
                )
                action = "Created" if created else "Updated"
                self.stdout.write(self.style.SUCCESS(f"  {action} global disable rule: {key}"))

        stale = FeatureFlagRule.objects.filter(
            scope=FeatureFlagRule.Scope.GLOBAL,
            note=PROD_DISABLE_NOTE,
        )
        if is_prod:
            stale = stale.exclude(flag__key__in=PROD_DISABLED_FLAGS)
        stale_keys = list(stale.values_list("flag__key", flat=True))
        if stale_keys:
            stale.delete()
            for key in stale_keys:
                self.stdout.write(f"  Removed stale seed-created disable rule: {key}")

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
