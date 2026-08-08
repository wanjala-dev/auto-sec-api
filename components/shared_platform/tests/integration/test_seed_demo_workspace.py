"""Integration tests — the idempotent demo-workspace seed (task #115).

Proves the three load-bearing properties:

1. From nothing, one run creates the demo logins, workspace, memberships,
   owner profile activation, and the exact live set of workspace-scoped flag
   rules — and prints the manual-reconnect checklist (secrets never seeded).
2. A second run is a strict NO-OP: ``changed=0`` and zero row deltas — safe to
   run on every api boot.
3. An existing login's password is NEVER rotated (only set at creation), and a
   drifted row (revoked membership, deactivated workspace) is repaired.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from components.shared_platform.cli.management.commands.seed_demo_workspace import (
    DEMO_WORKSPACE_FLAGS,
    DEMO_WORKSPACE_ID,
    DEMO_WORKSPACE_NAME,
)
from infrastructure.persistence.core.models import FeatureFlagRule
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _run() -> str:
    out = StringIO()
    call_command("seed_demo_workspace", stdout=out)
    return out.getvalue()


class TestSeedDemoWorkspace:
    def test_creates_everything_from_empty(self):
        output = _run()

        owner = CustomUser.objects.get(email="test@autosec.local")
        viewer = CustomUser.objects.get(email="member@autosec.local")
        assert owner.is_verified and owner.is_active
        assert viewer.is_verified and viewer.is_active
        assert owner.check_password("AutoSecTest2026!")
        assert viewer.check_password("AutoSecMember2026!")

        workspace = Workspace.objects.all_objects().get(id=DEMO_WORKSPACE_ID)
        assert workspace.workspace_name == DEMO_WORKSPACE_NAME
        assert workspace.status == "active" and workspace.is_active
        assert workspace.workspace_owner_id == owner.id

        owner_m = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
        assert (owner_m.role, owner_m.persona, owner_m.status) == ("owner", "admin", "active")
        viewer_m = WorkspaceMembership.objects.get(workspace=workspace, user=viewer)
        assert (viewer_m.role, viewer_m.persona, viewer_m.status) == ("viewer", "auditor", "active")

        assert str(UserProfile.objects.get(user=owner).active_workspace_id) == DEMO_WORKSPACE_ID

        rules = FeatureFlagRule.objects.filter(workspace=workspace, scope="workspace", enabled=True)
        assert {r.flag.key for r in rules} == set(DEMO_WORKSPACE_FLAGS)

        # No connections exist in a fresh DB → the full manual checklist prints.
        assert "MANUAL RECONNECT CHECKLIST" in output
        for fragment in ("AWS:", "GitHub:", "Slack:", "Log source:"):
            assert fragment in output

    def test_second_run_is_a_strict_noop(self):
        _run()
        counts_before = (
            CustomUser.objects.count(),
            Workspace.objects.all_objects().count(),
            WorkspaceMembership.objects.count(),
            FeatureFlagRule.objects.count(),
        )

        output = _run()

        assert "changed=0" in output
        counts_after = (
            CustomUser.objects.count(),
            Workspace.objects.all_objects().count(),
            WorkspaceMembership.objects.count(),
            FeatureFlagRule.objects.count(),
        )
        assert counts_after == counts_before

    def test_existing_password_never_rotated(self):
        _run()
        owner = CustomUser.objects.get(email="test@autosec.local")
        owner.set_password("OperatorChangedThis1!")
        owner.save(update_fields=["password"])

        _run()

        owner.refresh_from_db()
        assert owner.check_password("OperatorChangedThis1!")

    def test_repairs_drifted_rows(self):
        _run()
        workspace = Workspace.objects.all_objects().get(id=DEMO_WORKSPACE_ID)
        workspace.status = "inactive"
        workspace.is_active = False
        workspace.save(update_fields=["status", "is_active"])
        viewer_m = WorkspaceMembership.objects.get(workspace=workspace, user__email="member@autosec.local")
        viewer_m.status = WorkspaceMembership.Status.SUSPENDED
        viewer_m.save(update_fields=["status"])

        output = _run()

        workspace.refresh_from_db()
        viewer_m.refresh_from_db()
        assert workspace.status == "active" and workspace.is_active
        assert viewer_m.status == "active"
        assert "changed=0" not in output
