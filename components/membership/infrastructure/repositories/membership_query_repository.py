"""ORM membership query repository.

Extracted from ``components.team.infrastructure.repositories.team_membership_query_repository``.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist

from components.membership.domain.errors import (
    TeamMembershipRequiredError,
    WorkspaceMembershipRequiredError,
)
from infrastructure.persistence.team.models import Invitation, Team
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


class OrmMembershipQueryRepository:
    # Eager-load exactly what ``TeamSerializer`` reads per team row:
    # ``created_by`` / ``plan`` (forward FKs) plus the full ``UserSerializer``
    # over ``members`` — each member's profile (country FK, followers M2M +
    # followers_count), following_count (reverse ``followers`` M2M on the
    # user), sectors M2M, and the contributor_profile with its two M2Ms.
    # Without this every team on a list page fires its own FK queries and
    # every member fires its own profile/sectors/follower queries — a
    # two-level N+1
    # (see components/team/tests/integration/test_team_list_query_count.py).
    _SERIALIZER_SELECT_RELATED = ("workspace", "created_by", "plan")
    _SERIALIZER_PREFETCH_RELATED = (
        "members__profile__country",
        "members__profile__followers",
        "members__followers",
        # NOTE: members__sectors removed — the `sectors` app was dropped in the
        # auto-sec fork; the UserSerializer no longer reads it.
        "members__contributor_profile__contribution_means",
        "members__contributor_profile__preferred_locations",
    )

    @classmethod
    def _with_serializer_relations(cls, queryset):
        return queryset.select_related(*cls._SERIALIZER_SELECT_RELATED).prefetch_related(
            *cls._SERIALIZER_PREFETCH_RELATED
        )

    def list_user_teams(self, *, actor_id, user_id=None) -> list:
        if user_id:
            teams = Team.objects.filter(created_by=user_id, status=Team.ACTIVE)
        else:
            teams = Team.objects.filter(members__id=actor_id, status=Team.ACTIVE).distinct()
        return list(self._with_serializer_relations(teams))

    def get_team_detail(self, *, team_id: int, actor_id, is_staff=False, is_superuser=False):
        try:
            team = self._with_serializer_relations(Team.objects.all()).get(pk=team_id, status=Team.ACTIVE)
        except Team.DoesNotExist as exc:
            raise ObjectDoesNotExist("Team not found.") from exc

        if self._can_view_team_detail(team=team, actor_id=actor_id, is_staff=is_staff, is_superuser=is_superuser):
            return team
        raise TeamMembershipRequiredError("You must be a member of this team.")

    def list_workspace_teams(self, *, workspace_id, actor_id, team_name=None, is_staff=False, is_superuser=False):
        workspace = self._get_workspace(workspace_id=workspace_id)
        teams = Team.objects.filter(workspace=workspace, status=Team.ACTIVE)
        if team_name:
            teams = teams.filter(title=team_name)

        can_view_full = self._can_view_workspace(
            workspace=workspace,
            actor_id=actor_id,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

        # Owners, admins, and staff see ALL teams.
        # Regular members (contributors) only see teams they belong to.
        # This prevents the misleading UX where a contributor sees a
        # team, clicks it, and gets "you must be a member" error.
        if not self._is_privileged_viewer(
            workspace=workspace,
            actor_id=actor_id,
            is_staff=is_staff,
            is_superuser=is_superuser,
        ):
            teams = teams.filter(members__id=actor_id).distinct()

        return list(self._with_serializer_relations(teams)), can_view_full

    def list_workspace_team_members(self, *, workspace_id, actor_id, is_staff=False, is_superuser=False):
        workspace = self._get_accessible_workspace(
            workspace_id=workspace_id, actor_id=actor_id, is_staff=is_staff, is_superuser=is_superuser
        )
        # select_related("created_by"): the member loop below compares each
        # member against team.created_by — without this that FK is one query
        # per team. members__profile is prefetched so the inner loop is free.
        teams = list(
            Team.objects.filter(workspace_id=workspace.id, status=Team.ACTIVE)
            .select_related("created_by")
            .prefetch_related("members__profile")
        )
        joined_lookup = self._build_joined_lookup([team.id for team in teams])

        member_map = {}
        for team in teams:
            for member in team.members.all():
                email_key = (team.id, (member.email or "").strip().lower())
                joined_at = joined_lookup.get(email_key)
                if not joined_at and member == getattr(team, "created_by", None):
                    joined_at = team.created_at
                member_team_info = {"id": team.id, "title": team.title, "joined_at": joined_at}
                data = member_map.setdefault(member.id, {"user": member, "teams": []})
                data["teams"].append(member_team_info)

        # Include workspace-scoped members who don't sit on any team —
        # sponsors, auditors, board members, and the workspace owner.
        # Without this branch they'd be invisible in Directories → Contacts
        # because the team-walk above only sees Team.members. See ADR 0002.
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        ws_memberships = WorkspaceMembership.objects.filter(
            workspace_id=workspace.id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).select_related("user__profile")
        for ws_membership in ws_memberships:
            user = ws_membership.user
            if user is None:
                continue
            if user.id in member_map:
                continue  # already collected via a team membership
            member_map[user.id] = {"user": user, "teams": []}

        # Also include the workspace owner even if they don't have an
        # explicit WorkspaceMembership row (legacy data).
        owner = getattr(workspace, "workspace_owner", None)
        if owner is not None and owner.id not in member_map:
            member_map[owner.id] = {"user": owner, "teams": []}

        members = [entry["user"] for entry in member_map.values()]
        team_lookup = {entry["user"].id: entry["teams"] for entry in member_map.values()}
        return members, team_lookup

    def list_workspace_pending_invitations(self, *, workspace_id, actor_id, is_staff=False, is_superuser=False):
        workspace = self._get_accessible_workspace(
            workspace_id=workspace_id, actor_id=actor_id, is_staff=is_staff, is_superuser=is_superuser
        )
        invitations = (
            Invitation.objects.filter(workspace_id=workspace.id, status=Invitation.INVITED)
            .select_related("team")
            .order_by("-date_sent")
        )

        deduped = {}
        for invitation in invitations:
            email = (invitation.email or "").strip()
            if not email:
                continue
            key = email.lower()
            entry = deduped.setdefault(key, {"email": email, "latest_sent": invitation.date_sent, "teams": []})
            if invitation.date_sent and invitation.date_sent > entry["latest_sent"]:
                entry["latest_sent"] = invitation.date_sent
            team = invitation.team
            entry["teams"].append(
                {
                    "team_id": team.id if team else None,
                    "team_title": team.title if team else None,
                    "invitation_id": invitation.id,
                    "code": invitation.code,
                    # Magic-link token + persona + role surfaced so the
                    # Directories invitations tab can render copy-link UI for
                    # admins. The token is single-use and time-bound so it's
                    # safe to display.
                    "token": invitation.token or "",
                    "persona": invitation.persona or "",
                    "role": invitation.role or "",
                    "expires_at": invitation.expires_at,
                    "date_sent": invitation.date_sent,
                }
            )
        return list(deduped.values())

    @staticmethod
    def _build_joined_lookup(team_ids):
        if not team_ids:
            return {}
        invitations = (
            Invitation.objects.filter(team_id__in=team_ids, status=Invitation.ACCEPTED)
            .exclude(accepted_at__isnull=True)
            .values("team_id", "email", "accepted_at")
        )
        lookup = {}
        for invitation in invitations:
            email = (invitation["email"] or "").strip().lower()
            if not email:
                continue
            key = (invitation["team_id"], email)
            accepted_at = invitation["accepted_at"]
            existing = lookup.get(key)
            if not existing or accepted_at < existing:
                lookup[key] = accepted_at
        return lookup

    @staticmethod
    def _get_workspace(*, workspace_id):
        try:
            return Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist as exc:
            raise ObjectDoesNotExist("Workspace not found.") from exc

    def _get_accessible_workspace(self, *, workspace_id, actor_id, is_staff=False, is_superuser=False):
        workspace = self._get_workspace(workspace_id=workspace_id)
        if self._can_view_workspace(
            workspace=workspace, actor_id=actor_id, is_staff=is_staff, is_superuser=is_superuser
        ):
            return workspace
        raise WorkspaceMembershipRequiredError("You must belong to the organization to perform this action.")

    @staticmethod
    def _can_view_workspace(*, workspace, actor_id, is_staff=False, is_superuser=False):
        if is_staff or is_superuser:
            return True
        if str(workspace.workspace_owner_id) == str(actor_id):
            return True
        return WorkspaceMembership.objects.filter(
            workspace=workspace, user_id=actor_id, status=WorkspaceMembership.Status.ACTIVE
        ).exists()

    @staticmethod
    def _is_privileged_viewer(*, workspace, actor_id, is_staff=False, is_superuser=False):
        """Return True for users who should see ALL teams (owner, admin, staff).

        Regular members/contributors only see their own teams.
        """
        if is_staff or is_superuser:
            return True
        if str(workspace.workspace_owner_id) == str(actor_id):
            return True
        # Check if user has admin role in the workspace
        return WorkspaceMembership.objects.filter(
            workspace=workspace,
            user_id=actor_id,
            role__in=[WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN],
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists()

    @staticmethod
    def _can_view_team_detail(*, team, actor_id, is_staff=False, is_superuser=False):
        if is_staff or is_superuser:
            return True
        if str(team.workspace.workspace_owner_id) == str(actor_id):
            return True
        return team.members.filter(id=actor_id).exists()
