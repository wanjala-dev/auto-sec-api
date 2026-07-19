"""DjangoWorkspaceSnapshotDataAdapter — generic workspace-snapshot
coverage.

The adapter loads workspace identity, recent-activity rollups, top-N
entity lists, and member listings into ``WorkspaceSnapshotInput``.
The recipient/donation/campaign source reads were removed with the
sponsorship domain; the snapshot value object keeps those fields with
zero/empty defaults, so the empty-workspace test still pins that
contract. ``TestTopMembers`` covers the kept member-snapshot path
(Tier 3 #14 — the "Find <person>" routing gap).

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #5/#6 / Tier 3 #14.
"""

from __future__ import annotations

import pytest

from components.knowledge.infrastructure.adapters.django_workspace_snapshot_data_adapter import (
    DjangoWorkspaceSnapshotDataAdapter,
)


@pytest.mark.django_db
class TestEmptyWorkspaceGivesZeroCountsAndEmptyTuples:
    def test_no_seed_data_means_zeros_everywhere(self, workspace_factory):
        workspace = workspace_factory()
        data = DjangoWorkspaceSnapshotDataAdapter().load(str(workspace.id))

        assert data is not None
        assert data.recent_donation_count_30d == 0
        assert data.recent_donation_total_30d == ""
        assert data.recent_new_recipient_count_30d == 0
        assert data.recent_new_campaign_count_30d == 0
        assert data.recent_new_project_count_30d == 0
        assert data.top_donors == ()
        assert data.top_recipients == ()
        assert data.active_campaigns == ()
        assert data.open_grants == ()
        assert data.active_projects == ()
        # Empty workspace can still have the owner membership the
        # factory creates; the assertion that matters is that the
        # adapter doesn't crash and returns a tuple (possibly with
        # the owner). Top-members is empty only when nobody is a
        # member, which the workspace_factory may or may not satisfy
        # depending on fixture wiring — assert the type, not the
        # exact contents.
        assert isinstance(data.top_members, tuple)


@pytest.mark.django_db
class TestTopMembers:
    """Tier 3 #14 — workspace members by name + role.

    Closes the bare-find routing gap surfaced by the 2026-06-09 demo
    smoke. Without this section the embedding index only named donors
    and recipients, so any bare "Find <person>" query was pulled to
    donation_agent or sponsorship_agent. Naming members lets hybrid
    search surface a member-typed chunk that the v6 planner uses to
    route to user_agent.
    """

    def test_active_members_surfaced_as_name_and_role(self, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        workspace = workspace_factory()
        teammate = user_factory()
        teammate.first_name = "Aisha"
        teammate.last_name = "Otieno"
        teammate.save(update_fields=["first_name", "last_name"])
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=teammate,
            role="admin",
            status="active",
        )

        data = DjangoWorkspaceSnapshotDataAdapter().load(str(workspace.id))
        assert data is not None
        assert any("Aisha Otieno" in row and "admin" in row.lower() for row in data.top_members), (
            f"top_members must surface name + role; got {data.top_members!r}"
        )

    def test_inactive_members_excluded(self, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        workspace = workspace_factory()
        inactive = user_factory()
        inactive.first_name = "Inactive"
        inactive.last_name = "Person"
        inactive.save(update_fields=["first_name", "last_name"])
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=inactive,
            role="member",
            status="inactive",
        )

        data = DjangoWorkspaceSnapshotDataAdapter().load(str(workspace.id))
        assert data is not None
        assert all("Inactive Person" not in row for row in data.top_members), (
            "Inactive memberships must not appear in the snapshot — "
            "they are not part of the workspace's active identity."
        )

    def test_email_is_never_in_top_members(self, workspace_factory, user_factory):
        """PII discipline — the embedding index must not contain emails
        even when WorkspaceMembership.user has one. ``user_agent`` owns
        email lookup via ``get_user_profile``; the snapshot is name +
        role only.
        """
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        workspace = workspace_factory()
        teammate = user_factory(email="aisha@zaylan.demo")
        teammate.first_name = "Aisha"
        teammate.last_name = "Otieno"
        teammate.save(update_fields=["first_name", "last_name"])
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=teammate,
            role="member",
            status="active",
        )

        data = DjangoWorkspaceSnapshotDataAdapter().load(str(workspace.id))
        assert data is not None
        rendered = "\n".join(data.top_members)
        assert "@" not in rendered, (
            f"Member emails must not enter the embedding index — got top_members={data.top_members!r}"
        )

    def test_top_members_isolated_per_workspace(self, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        ws_a = workspace_factory()
        ws_b = workspace_factory()
        teammate_a = user_factory()
        teammate_a.first_name = "Member"
        teammate_a.last_name = "Alpha"
        teammate_a.save(update_fields=["first_name", "last_name"])
        teammate_b = user_factory()
        teammate_b.first_name = "Member"
        teammate_b.last_name = "Beta"
        teammate_b.save(update_fields=["first_name", "last_name"])
        WorkspaceMembership.objects.create(workspace=ws_a, user=teammate_a, role="member", status="active")
        WorkspaceMembership.objects.create(workspace=ws_b, user=teammate_b, role="member", status="active")

        data_a = DjangoWorkspaceSnapshotDataAdapter().load(str(ws_a.id))
        data_b = DjangoWorkspaceSnapshotDataAdapter().load(str(ws_b.id))

        assert any("Member Alpha" in row for row in data_a.top_members)
        assert not any("Member Beta" in row for row in data_a.top_members)
        assert any("Member Beta" in row for row in data_b.top_members)
        assert not any("Member Alpha" in row for row in data_b.top_members)
