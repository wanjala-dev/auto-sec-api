"""Seed the system WorkspaceRole templates for Auto-Sec.

System roles are shared across every workspace (``workspace=None``,
``is_system=True``) and hold the canonical capability bundles. The permission
keys MUST stay in lockstep with
``components.workspace.api.groups_controller.VALID_PERMISSION_KEYS`` (the
security catalog — findings/detections/cases/playbooks/agents/assets/audit).

The auto-sec fork inherited the WorkspaceRole model but not the seed, so member
role changes 400'd ("Unknown role slug") until this ran. Idempotent
(update_or_create on slug); safe to re-run and wired into boot seeding.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

# Kept intentionally in code (not imported from the controller) so this command
# has no API-layer dependency, but the set MUST match VALID_PERMISSION_KEYS.
_ALL = [
    "manage_settings",
    "manage_billing",
    "manage_integrations",
    "manage_users",
    "manage_permissions",
    "view_findings",
    "manage_findings",
    "view_detections",
    "manage_detections",
    "view_cases",
    "manage_cases",
    "run_playbooks",
    "manage_playbooks",
    "view_agents",
    "manage_agents",
    "view_assets",
    "manage_assets",
    "view_audit",
    "view_reports",
    "manage_reports",
    "view_writing",
    "manage_writing",
]

# Analyst — can work findings/cases and run playbooks, read everything else.
_MEMBER = [
    "view_findings",
    "manage_findings",
    "view_detections",
    "view_cases",
    "manage_cases",
    "run_playbooks",
    "view_agents",
    "view_assets",
    "view_audit",
    "view_reports",
    # Analysts author incident reports / RCAs (incl. AI-assist).
    "view_writing",
    "manage_writing",
]

# Read-only observer.
_VIEWER = [
    "view_findings",
    "view_detections",
    "view_cases",
    "view_agents",
    "view_assets",
    "view_audit",
    "view_reports",
    "view_writing",
]

# (slug, name, description, permissions)
SYSTEM_ROLE_SEEDS = [
    ("owner", "Owner", "Full control. One per workspace. Can transfer ownership and delete the workspace.", _ALL),
    ("admin", "Root", "Manage the workspace and everything inside it. Cannot transfer ownership.", _ALL),
    ("member", "Analyst", "Triage findings, work cases, run playbooks. Read-only elsewhere.", _MEMBER),
    ("viewer", "Viewer", "Read-only access to the SOC surfaces.", _VIEWER),
]


class Command(BaseCommand):
    help = "Seed / refresh the system WorkspaceRole templates (owner/admin/member/viewer)."

    def handle(self, *args, **options):
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        created = 0
        updated = 0
        for slug, name, description, permissions in SYSTEM_ROLE_SEEDS:
            _, was_created = WorkspaceRole.objects.update_or_create(
                workspace=None,
                slug=slug,
                defaults={
                    "name": name,
                    "description": description,
                    "permissions": permissions,
                    "is_system": True,
                },
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(f"system workspace roles seeded (created={created} updated={updated})"))
