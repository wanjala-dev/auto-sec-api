"""Backfill workspace/team membership records for existing org data."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from infrastructure.persistence.team.models import Team, TeamMembership
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


def _system_role(slug: str):
    """The seeded system ``WorkspaceRole`` for *slug*, or None if unseeded.

    ``WorkspaceMembership.workspace_role`` is the CAPABILITY-backed role — the
    model documents null as "a hard bug from Phase 2 onward". A backfill that
    sets only the legacy ``role`` string therefore manufactures exactly the rows
    the RBAC model considers broken: the member has a role name but no
    capabilities behind it. Resolving it here keeps repaired rows first-class.

    Best-effort by design: on a database where the system roles have not been
    seeded yet (``seed_workspace_roles``) this returns None and the row is
    created exactly as before — never a crash during a data repair.
    """
    from infrastructure.persistence.workspaces.models import WorkspaceRole

    return WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug=slug).first()


class Command(BaseCommand):
    help = "Backfill WorkspaceMembership and TeamMembership rows from existing owners and team members."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-id",
            dest="workspace_id",
            help="Limit backfill to a single workspace UUID.",
        )
        parser.add_argument(
            "--team-id",
            dest="team_id",
            help="Limit backfill to a single team id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report changes without persisting.",
        )

    def handle(self, *args, **options):
        workspace_id = options.get("workspace_id")
        team_id = options.get("team_id")
        dry_run = bool(options.get("dry_run"))

        workspaces = Workspace.objects.all()
        if workspace_id:
            workspaces = workspaces.filter(id=workspace_id)

        # ACTIVE teams only. ``Team`` has no soft-delete manager, so a bare
        # ``.all()`` walks DELETED teams too — and this command GRANTS workspace
        # access to every team member it finds. Backfilling from a deleted team
        # silently resurrects access that an admin had explicitly removed, which
        # on a security product is an access-control regression, not a cosmetic
        # one. (Caught 2026-08-08 while repairing the backfill's fork-drifted
        # tests, whose "deleted team does not trigger backfill" invariant had
        # been unverified since the migration it pointed at was removed.)
        teams = Team.objects.filter(status=Team.ACTIVE)
        if team_id:
            teams = teams.filter(id=team_id)
        if workspace_id:
            teams = teams.filter(workspace_id=workspace_id)

        created_workspace_memberships = 0
        updated_workspace_memberships = 0
        created_team_memberships = 0
        updated_team_memberships = 0

        with transaction.atomic():
            for workspace in workspaces.iterator():
                owner_id = workspace.workspace_owner_id
                if owner_id:
                    created, updated = self._ensure_workspace_owner(workspace, owner_id, dry_run=dry_run)
                    created_workspace_memberships += created
                    updated_workspace_memberships += updated

            for team in teams.iterator():
                created, updated = self._ensure_team_memberships(team, dry_run=dry_run)
                created_team_memberships += created
                updated_team_memberships += updated

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            f"Workspace memberships: {created_workspace_memberships} created, {updated_workspace_memberships} updated"
        )
        self.stdout.write(f"Team memberships: {created_team_memberships} created, {updated_team_memberships} updated")

    def _ensure_workspace_owner(self, workspace, owner_id, *, dry_run: bool) -> tuple[int, int]:
        # Persona for the workspace owner is derived from workspace_type
        # so the frontend dashboard experience matches the backend role
        # policy on first paint. Mirrors `ensure_workspace_membership`
        # in workspace_utils.py — see ADR 0002. Without setting it
        # explicitly, the model default of CONTRIBUTOR sticks and the
        # owner renders the contributor sidebar despite having admin
        # visible_sections from the API. Confirmed in production where
        # an owner showed up as role=owner but persona=contributor.
        if getattr(workspace, "workspace_type", None) == "personal":
            owner_persona = WorkspaceMembership.Persona.PRIVATE
        else:
            owner_persona = WorkspaceMembership.Persona.ADMIN

        created = 0
        updated = 0
        membership, was_created = WorkspaceMembership.objects.get_or_create(
            workspace_id=workspace.id,
            user_id=owner_id,
            defaults={
                "role": WorkspaceMembership.Role.OWNER,
                "workspace_role": _system_role(WorkspaceMembership.Role.OWNER),
                "persona": owner_persona,
                "status": WorkspaceMembership.Status.ACTIVE,
                "accepted_at": workspace.created_at,
            },
        )
        if was_created:
            created += 1
            return created, updated

        updates = []
        if membership.role != WorkspaceMembership.Role.OWNER:
            membership.role = WorkspaceMembership.Role.OWNER
            updates.append("role")
        # Backfill persona for owner rows created before this command set
        # it, where the model default left them as CONTRIBUTOR. Only
        # rewrite when the stored value is actually CONTRIBUTOR — leaves
        # legitimately customised personas (AGENTIC, BOARD_MEMBER, etc.)
        # alone in case anyone deliberately set one.
        if membership.persona == WorkspaceMembership.Persona.CONTRIBUTOR:
            membership.persona = owner_persona
            updates.append("persona")
        if membership.status != WorkspaceMembership.Status.ACTIVE:
            membership.status = WorkspaceMembership.Status.ACTIVE
            updates.append("status")
        if membership.accepted_at is None:
            membership.accepted_at = workspace.created_at
            updates.append("accepted_at")
        if updates:
            if not dry_run:
                membership.save(update_fields=[*updates, "updated_at"])
            updated += 1
        return created, updated

    def _ensure_team_memberships(self, team, *, dry_run: bool) -> tuple[int, int]:
        created = 0
        updated = 0
        workspace_id = team.workspace_id

        # Ensure team lead membership for creator.
        if team.created_by_id:
            membership, was_created = TeamMembership.objects.get_or_create(
                team_id=team.id,
                user_id=team.created_by_id,
                defaults={
                    "role": TeamMembership.Role.LEAD,
                    "status": TeamMembership.Status.ACTIVE,
                },
            )
            if was_created:
                created += 1
            elif membership.role != TeamMembership.Role.LEAD:
                membership.role = TeamMembership.Role.LEAD
                if not dry_run:
                    membership.save(update_fields=["role", "updated_at"])
                updated += 1

            # Ensure workspace membership for team creator.
            if workspace_id:
                WorkspaceMembership.objects.get_or_create(
                    workspace_id=workspace_id,
                    user_id=team.created_by_id,
                    defaults={
                        "role": WorkspaceMembership.Role.MEMBER,
                        "workspace_role": _system_role(WorkspaceMembership.Role.MEMBER),
                        "status": WorkspaceMembership.Status.ACTIVE,
                    },
                )

        # Ensure team editor membership for team members.
        member_ids = list(team.members.values_list("id", flat=True))
        for member_id in member_ids:
            membership, was_created = TeamMembership.objects.get_or_create(
                team_id=team.id,
                user_id=member_id,
                defaults={
                    "role": TeamMembership.Role.EDITOR,
                    "status": TeamMembership.Status.ACTIVE,
                },
            )
            if was_created:
                created += 1

            # Ensure workspace membership for team members.
            if workspace_id:
                WorkspaceMembership.objects.get_or_create(
                    workspace_id=workspace_id,
                    user_id=member_id,
                    defaults={
                        "role": WorkspaceMembership.Role.MEMBER,
                        "workspace_role": _system_role(WorkspaceMembership.Role.MEMBER),
                        "status": WorkspaceMembership.Status.ACTIVE,
                    },
                )

        return created, updated
