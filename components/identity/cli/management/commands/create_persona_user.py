"""Create a single persona user for a workspace.

Like ``createsuperuser`` but creates a user with a specific persona role
(admin, contributor, sponsor, or personal) and wires them into the workspace.

Usage:
    python manage.py create_persona_user --role admin --workspace-id <UUID>
    python manage.py create_persona_user --role sponsor --workspace-id <UUID> --email donor@example.com
    python manage.py create_persona_user --role contributor --workspace-id <UUID> --password secret
    python manage.py create_persona_user --role personal --email jane@example.com
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.core.management import BaseCommand, CommandError
from django.db import transaction

VALID_ROLES = ("admin", "contributor", "sponsor", "personal")


class Command(BaseCommand):
    help = "Create a user with a specific persona role (admin, contributor, sponsor, personal)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--role",
            required=True,
            choices=VALID_ROLES,
            help="Persona role: admin, contributor, sponsor, or personal",
        )
        parser.add_argument(
            "--workspace-id", required=False, help="Target workspace UUID (required for admin/contributor/sponsor)"
        )
        parser.add_argument("--email", required=False, help="Email address (default: <role>@test.octopi.dev)")
        parser.add_argument("--username", required=False, help="Username (default: derived from email)")
        parser.add_argument("--first-name", required=False, help="First name (default: derived from role)")
        parser.add_argument("--last-name", required=False, default="User", help="Last name (default: User)")
        parser.add_argument("--password", default="testpass123", help="Password (default: testpass123)")

    def handle(self, *args, **options):
        role = options["role"]
        workspace_id = options.get("workspace_id")
        email = options.get("email") or f"{role}@test.octopi.dev"
        username = options.get("username") or email.split("@")[0]
        first_name = options.get("first_name") or role.capitalize()
        last_name = options["last_name"]
        password = options["password"]

        if role in ("admin", "contributor", "sponsor") and not workspace_id:
            raise CommandError(f"--workspace-id is required for role '{role}'")

        Workspace = django_apps.get_model("workspaces", "Workspace")
        workspace = None
        if workspace_id:
            workspace = Workspace.objects.filter(id=workspace_id).first()
            if not workspace:
                raise CommandError(f"Workspace not found: {workspace_id}")

        with transaction.atomic():
            user = self._get_or_create_user(email, username, first_name, last_name, password)
            setup_fn = getattr(self, f"_setup_{role}")
            setup_fn(user, workspace)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  Created {role} user:\n"
                f"  Email:     {email}\n"
                f"  Password:  {password}\n"
                f"  Workspace: {workspace.workspace_name if workspace else 'personal (own)'}\n"
            )
        )

    def _get_or_create_user(self, email, username, first_name, last_name, password):
        CustomUser = django_apps.get_model("users", "CustomUser")
        user = CustomUser.objects.filter(email=email).first()
        if user:
            self.stdout.write(f"  User '{email}' already exists — reusing")
            return user
        user = CustomUser.objects.create_user(username=username, email=email, password=password)
        user.first_name = first_name
        user.last_name = last_name
        user.is_verified = True
        user.is_onboard_complete = True
        user.save(update_fields=["first_name", "last_name", "is_verified", "is_onboard_complete"])
        self.stdout.write(self.style.SUCCESS(f"  + Created user '{email}'"))
        return user

    def _ensure_profile(self, user, workspace):
        UserProfile = django_apps.get_model("users", "UserProfile")
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if workspace and not profile.active_workspace_id:
            profile.active_workspace_id = workspace.id
            profile.save(update_fields=["active_workspace_id"])

    def _ensure_team(self, workspace):
        Team = django_apps.get_model("team", "Team")
        # Reuse the workspace's bootstrap home team instead of creating a
        # separate "Default Team" (that parallel team was the dev-seed duplicate
        # — nav rework). Only create a "General" default if none exists.
        team = (
            Team.objects.filter(workspace=workspace, is_default=True).first()
            or Team.objects.filter(workspace=workspace, title__in=("General", "Contributors", "Family"))
            .order_by("id")
            .first()
        )
        if team is None:
            team = Team.objects.create(
                workspace=workspace,
                title="General",
                created_by=workspace.workspace_owner,
                status="active",
                is_default=True,
            )
        elif not team.is_default:
            team.is_default = True
            team.save(update_fields=["is_default"])
        return team

    def _setup_admin(self, user, workspace):
        WorkspaceMembership = django_apps.get_model("workspaces", "WorkspaceMembership")
        Team = django_apps.get_model("team", "Team")

        membership, created = WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": "admin", "status": "active"},
        )
        if not created and membership.role != "admin":
            membership.role = "admin"
            membership.save(update_fields=["role"])

        team = self._ensure_team(workspace)
        if not team.members.filter(id=user.id).exists():
            team.members.add(user)

        # Admin needs to be created_by on a team for role resolver
        admin_team, _ = Team.objects.get_or_create(
            workspace=workspace,
            title="Admin Team",
            defaults={"created_by": user, "status": "active"},
        )
        if not admin_team.members.filter(id=user.id).exists():
            admin_team.members.add(user)

        self._ensure_profile(user, workspace)
        self.stdout.write(f"  Wired as admin in '{workspace.workspace_name}'")

    def _setup_contributor(self, user, workspace):
        WorkspaceMembership = django_apps.get_model("workspaces", "WorkspaceMembership")

        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": "member", "status": "active"},
        )
        team = self._ensure_team(workspace)
        if not team.members.filter(id=user.id).exists():
            team.members.add(user)

        self._ensure_profile(user, workspace)
        self.stdout.write(f"  Wired as contributor in '{workspace.workspace_name}'")

    def _setup_sponsor(self, user, workspace):
        if not workspace.followers.filter(id=user.id).exists():
            workspace.followers.add(user)

        self._ensure_profile(user, workspace)
        self.stdout.write(f"  Wired as sponsor/follower of '{workspace.workspace_name}'")

    def _setup_personal(self, user, workspace):
        Workspace = django_apps.get_model("workspaces", "Workspace")
        UserProfile = django_apps.get_model("users", "UserProfile")

        personal_ws, created = Workspace.objects.get_or_create(
            workspace_owner=user,
            workspace_type="personal",
            defaults={
                "workspace_name": f"{user.first_name}'s Space",
                "status": "active",
                "privacy": Workspace.PRIVATE,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  + Created personal workspace '{personal_ws.workspace_name}'"))

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.active_workspace_id = personal_ws.id
        profile.save(update_fields=["active_workspace_id"])
        self.stdout.write(f"  Wired as personal user with workspace '{personal_ws.workspace_name}'")
