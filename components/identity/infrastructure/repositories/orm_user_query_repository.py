"""ORM adapter implementing UserQueryPort.

This adapter provides raw ORM model queries for controller and serialization logic.
It returns ORM models directly rather than domain entities.
"""

from __future__ import annotations

from django.db.models import Q

from components.identity.application.ports.user_query_port import UserQueryPort


class OrmUserQueryRepository(UserQueryPort):
    """Concrete adapter backed by Django ORM for query operations."""

    def get_by_id(self, user_id, with_profile: bool = False):
        """Get user by ID, optionally with profile pre-fetched."""
        from infrastructure.persistence.users.models import CustomUser

        qs = CustomUser.objects.all()
        if with_profile:
            qs = qs.select_related("profile", "contributor_profile")
        try:
            return qs.get(id=user_id)
        except CustomUser.DoesNotExist:
            return None

    def get_by_email(self, email: str):
        """Get user by email."""
        from infrastructure.persistence.users.models import CustomUser

        try:
            return CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return None

    def find_by_email_and_username(self, email: str, username: str):
        """Find users matching email and username."""
        from infrastructure.persistence.users.models import CustomUser

        return CustomUser.objects.filter(email=email, username=username)

    def get_queryset(self):
        """Return the base user queryset with profile pre-fetched.

        Unscoped — see the port docstring before serving this to a caller.
        """
        from infrastructure.persistence.users.models import CustomUser

        return CustomUser.objects.select_related("profile", "contributor_profile")

    def get_queryset_visible_to(self, actor):
        """Users sharing a workspace with ``actor`` (plus the actor).

        This is the single canonical answer to "which users may this caller
        see" — the tenant boundary for user data. autosec is single-database
        with application-enforced isolation, so this filter is the only thing
        standing between a caller and every other tenant's directory.

        **Tenancy predicate: OWNS the workspace, or holds an ACTIVE
        ``WorkspaceMembership`` in it.** That is deliberately the exact rule
        already carried by
        ``components.workspace.infrastructure.repositories.workspace_query_repository.WorkspaceQueryRepository.scope_to_user``
        and ``components.membership.api.permissions.user_is_active_workspace_member``
        — three seams, one rule, so a change to one belongs in all three.

        The owner arm is not cosmetic. ``Workspace.workspace_owner`` is a
        column on the workspace, and the ``WorkspaceMembership`` row for the
        owner is scaffolding written *alongside* it. The codebase already
        knows those two can disagree — ``membership_query_repository
        .list_workspace_team_members`` carries an explicit "include the
        workspace owner even if they don't have an explicit
        WorkspaceMembership row (legacy data)" branch. Without the owner arm
        here, an owner whose scaffolding row is missing is invisible to their
        own colleagues *and* cannot see them: the tenant boundary would be
        drawn from a derived table rather than from ownership itself.

        Membership status still matters on the membership arm: an ``invited``
        or ``suspended`` row is not an active tenancy and must not grant
        visibility. Nothing wider is admitted — not followers, not
        pending/revoked memberships, and not a ``Team.members`` walk. The
        roster endpoint (``/membership/members/``) does walk teams, but it
        answers a different question: it is object-scoped to one workspace the
        caller has *already* been authorized on, whereas this predicate decides
        which tenants a caller may see people from at all. Widening this to
        match the roster would let a stale team row re-open the boundary.

        Ordered because this feeds paginated reads: ``CustomUser`` declares no
        ``Meta.ordering``, and paginating an unordered queryset lets rows
        repeat or vanish between pages. ``id`` breaks ties on the
        ``auto_now_add`` timestamp, which collides for bulk-created rows.
        """
        from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

        base = self.get_queryset().order_by("-created_at", "id")

        if actor is None or not getattr(actor, "is_authenticated", False):
            return base.none()

        if getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False):
            return base

        # Workspaces the actor is a tenant of: owned OR actively joined.
        owned_workspace_ids = Workspace.objects.filter(workspace_owner_id=actor.id).values_list("id", flat=True)
        joined_workspace_ids = WorkspaceMembership.objects.filter(
            user_id=actor.id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).values_list("workspace_id", flat=True)
        actor_workspace_ids = set(owned_workspace_ids) | set(joined_workspace_ids)

        # People inside those workspaces: same predicate, applied the other way.
        member_user_ids = WorkspaceMembership.objects.filter(
            workspace_id__in=actor_workspace_ids,
            status=WorkspaceMembership.Status.ACTIVE,
        ).values_list("user_id", flat=True)
        owner_user_ids = Workspace.objects.filter(id__in=actor_workspace_ids).values_list(
            "workspace_owner_id", flat=True
        )

        # The actor is always visible to themselves, including before they
        # have joined (or after they have left) any workspace.
        return base.filter(Q(id__in=member_user_ids) | Q(id__in=owner_user_ids) | Q(id=actor.id))

    def get_profile(self, user_id):
        """Get user profile by user ID."""
        from infrastructure.persistence.users.models import UserProfile

        try:
            return UserProfile.objects.get(user_id=user_id)
        except UserProfile.DoesNotExist:
            return None

    def list_pending_invitations(self, email: str):
        """List pending invitations for an email."""
        from infrastructure.persistence.team.models import Invitation

        return Invitation.objects.filter(email=email, status=Invitation.INVITED).order_by("-id")

    def get_system_actor(self):
        """Get system actor (superuser or staff) for audit events."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.filter(is_superuser=True).first() or User.objects.filter(is_staff=True).first()
