"""Idempotent demo-workspace seed — recreate (or verify) the seeded demo logins.

Mirrors the live demo environment exactly (grounded against the cluster DB on
2026-08-08, task #115):

- owner   test@autosec.local    (username ``test``,   role owner,  persona admin)
- viewer  member@autosec.local  (username ``member``, role viewer, persona auditor)
- workspace ``cc287133-b53c-43c8-9000-2873f8c8a1e3`` "Auto-Sec Test"
  (teamspace, status active, is_active) owned by the owner
- workspace-scoped feature-flag rules (enabled) for exactly the live set:
  cloud_asset_graph, cloud_posture, code_security, container_security,
  sample_data_mode

SECRETS ARE NOT SEEDABLE. Integration connections (AWS role ARN, GitHub PAT,
Slack webhook) carry encrypted credentials that only a human can re-enter —
the command inspects which connection types exist for the workspace and prints
a manual-reconnect checklist for whatever is missing.

Idempotent + fast + safe for every boot: existing rows are never rewritten
unless they drifted from the demo contract, passwords are only set when a user
is CREATED (an existing login's password is never rotated), and the run
reports ``changed=0`` when everything already matches — wired into the api
startup beside seed_subscription_tiers / seed_feature_flags.

Usage:
    python manage.py seed_demo_workspace

Env overrides (defaults = the known demo logins):
    DEMO_OWNER_EMAIL / DEMO_OWNER_PASSWORD
    DEMO_VIEWER_EMAIL / DEMO_VIEWER_PASSWORD
    DEMO_WORKSPACE_ID
"""

from __future__ import annotations

import os

from django.core.management import BaseCommand

from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule

DEMO_WORKSPACE_ID = "cc287133-b53c-43c8-9000-2873f8c8a1e3"
DEMO_WORKSPACE_NAME = "Auto-Sec Test"

# The exact set of workspace-scoped flag rules live on the demo workspace.
DEMO_WORKSPACE_FLAGS = (
    "feature.cloud_asset_graph",
    "feature.cloud_posture",
    "feature.code_security",
    "feature.container_security",
    "feature.sample_data_mode",
)

# Connection models that carry manual secrets, with the human instruction for
# re-establishing each. (model name → checklist line)
_CONNECTION_CHECKLIST = (
    (
        "AwsOrganizationConnection",
        "AWS: reconnect the audit role (Settings ▸ Integrations ▸ AWS — role ARN + external id, then /verify/).",
    ),
    (
        "WorkspaceLogSource",
        "Log source: re-add the S3/CloudWatch log source (Settings ▸ Integrations ▸ Log sources).",
    ),
    (
        "VcsConnection",
        "GitHub: reconnect the VCS connection (Settings ▸ Integrations ▸ Code repositories — PAT + repo allowlist).",
    ),
    (
        "DeliveryConnection",
        "Slack: reconnect the delivery channel (Settings ▸ Integrations ▸ Notifications — webhook URL).",
    ),
)


class Command(BaseCommand):
    help = "Idempotently seed the demo workspace (users, memberships, flag rules) and print the manual-reconnect checklist."

    def handle(self, *args, **options):
        from infrastructure.persistence.users.models import CustomUser, UserProfile
        from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

        owner_email = os.environ.get("DEMO_OWNER_EMAIL", "test@autosec.local")
        owner_password = os.environ.get("DEMO_OWNER_PASSWORD", "AutoSecTest2026!")
        viewer_email = os.environ.get("DEMO_VIEWER_EMAIL", "member@autosec.local")
        viewer_password = os.environ.get("DEMO_VIEWER_PASSWORD", "AutoSecMember2026!")
        workspace_id = os.environ.get("DEMO_WORKSPACE_ID", DEMO_WORKSPACE_ID)

        changed = 0

        def _ensure_user(email: str, username: str, password: str):
            nonlocal changed
            user, created = CustomUser.objects.get_or_create(
                email=email,
                defaults={"username": username, "is_verified": True, "is_active": True},
            )
            if created:
                # Password is only ever set at creation — an existing demo
                # login's credential is never silently rotated by a boot.
                user.set_password(password)
                user.save(update_fields=["password"])
                changed += 1
                self.stdout.write(self.style.SUCCESS(f"created user {email}"))
                return user
            fixes = []
            if not user.is_verified:
                user.is_verified = True
                fixes.append("is_verified")
            if not user.is_active:
                user.is_active = True
                fixes.append("is_active")
            if fixes:
                user.save(update_fields=fixes)
                changed += 1
                self.stdout.write(self.style.WARNING(f"repaired user {email}: {', '.join(fixes)}"))
            return user

        owner = _ensure_user(owner_email, "test", owner_password)
        viewer = _ensure_user(viewer_email, "member", viewer_password)

        # all_objects: the default Workspace manager filters status="active" —
        # a deactivated demo workspace must be FOUND and repaired, not
        # re-created onto the same pk (IntegrityError).
        workspace, created = Workspace.objects.all_objects().get_or_create(
            id=workspace_id,
            defaults={
                "workspace_name": DEMO_WORKSPACE_NAME,
                "workspace_type": "teamspace",
                "workspace_owner": owner,
                "status": "active",
                "is_active": True,
            },
        )
        if created:
            changed += 1
            self.stdout.write(self.style.SUCCESS(f"created workspace {workspace_id} ({DEMO_WORKSPACE_NAME})"))
        else:
            fixes = []
            if workspace.workspace_name != DEMO_WORKSPACE_NAME:
                workspace.workspace_name = DEMO_WORKSPACE_NAME
                fixes.append("workspace_name")
            if workspace.status != "active":
                workspace.status = "active"
                fixes.append("status")
            if not workspace.is_active:
                workspace.is_active = True
                fixes.append("is_active")
            if workspace.workspace_owner_id != owner.id:
                workspace.workspace_owner = owner
                fixes.append("workspace_owner")
            if fixes:
                workspace.save(update_fields=fixes)
                changed += 1
                self.stdout.write(self.style.WARNING(f"repaired workspace: {', '.join(fixes)}"))

        def _ensure_membership(user, role: str, persona: str):
            nonlocal changed
            membership, m_created = WorkspaceMembership.objects.get_or_create(
                workspace=workspace,
                user=user,
                defaults={"role": role, "persona": persona, "status": "active"},
            )
            if m_created:
                changed += 1
                self.stdout.write(self.style.SUCCESS(f"created membership {user.email} role={role}"))
                return
            fixes = []
            if membership.role != role:
                membership.role = role
                fixes.append("role")
            if membership.persona != persona:
                membership.persona = persona
                fixes.append("persona")
            if membership.status != "active":
                membership.status = "active"
                fixes.append("status")
            if fixes:
                membership.save(update_fields=fixes)
                changed += 1
                self.stdout.write(self.style.WARNING(f"repaired membership {user.email}: {', '.join(fixes)}"))

        _ensure_membership(owner, "owner", "admin")
        _ensure_membership(viewer, "viewer", "auditor")

        # The owner's HUD resolves through the profile's active workspace.
        profile, p_created = UserProfile.objects.get_or_create(user=owner)
        if p_created or not profile.active_workspace_id:
            if str(profile.active_workspace_id or "") != str(workspace.id):
                profile.active_workspace_id = workspace.id
                profile.save(update_fields=["active_workspace_id"])
                changed += 1
                self.stdout.write(self.style.SUCCESS(f"set owner active workspace → {workspace.id}"))

        # Workspace-scoped feature-flag rules — mirror EXACTLY the live demo set.
        flags_changed = 0
        for key in DEMO_WORKSPACE_FLAGS:
            flag, f_created = FeatureFlag.objects.get_or_create(key=key, defaults={"default_enabled": False})
            rule, r_created = FeatureFlagRule.objects.get_or_create(
                flag=flag,
                scope=FeatureFlagRule.Scope.WORKSPACE,
                workspace=workspace,
                defaults={"enabled": True},
            )
            if r_created:
                flags_changed += 1
                self.stdout.write(self.style.SUCCESS(f"created workspace flag rule {key}=on"))
            elif not rule.enabled:
                rule.enabled = True
                rule.save(update_fields=["enabled"])
                flags_changed += 1
                self.stdout.write(self.style.WARNING(f"re-enabled workspace flag rule {key}"))
        if flags_changed:
            from components.shared_platform.infrastructure.services.feature_flags import (
                bump_feature_flags_version,
            )

            bump_feature_flags_version()
            changed += flags_changed

        self._report_connections(workspace)

        self.stdout.write(self.style.SUCCESS(f"seed_demo_workspace done changed={changed}"))

    def _report_connections(self, workspace) -> None:
        """SECRETS ARE NOT SEEDABLE — print what must be reconnected by hand."""
        from infrastructure.persistence.integrations import models as integrations_models

        missing = []
        for model_name, instruction in _CONNECTION_CHECKLIST:
            model = getattr(integrations_models, model_name)
            if model.objects.filter(workspace_id=workspace.id).exists():
                self.stdout.write(f"connection present: {model_name}")
            else:
                missing.append(instruction)
        if missing:
            self.stdout.write(self.style.WARNING("MANUAL RECONNECT CHECKLIST (secrets are never seeded):"))
            for line in missing:
                self.stdout.write(self.style.WARNING(f"  [ ] {line}"))
