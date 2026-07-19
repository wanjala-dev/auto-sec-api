"""Seed a dedicated user + workspace + membership for load testing.

Idempotent. Safe to run repeatedly. Creates:
- ``loadtest@wanjala.local`` with a known password
- ``Load Test Workspace`` (teamspace, status=active), owned by that user
- ``WorkspaceMembership`` with role=owner + workspace_role=Owner system
  role + persona=admin + status=active

Used by ``tests/load/`` (see ``.claude/rules/load-testing.md``). The credentials
this command prints are what go into ``tests/load/.env.load`` as
``LOAD_SMOKE_EMAIL`` / ``LOAD_SMOKE_PASSWORD`` / ``LOAD_SMOKE_WORKSPACE_ID``.

Why a dedicated seed and not ``bootstrap_dev``:
- ``bootstrap_dev`` reuses persona accounts that may have other use, may have
  2FA toggled by other tests, and depend on an existing teamspace.
- Load tests need a stable, isolated, predictable account that's safe to hammer.
- This command is the canonical seed. Add it to your local stack init and to
  the EC2 ``configure_site`` step if you want demo smoke runnable end-to-end.

Env overrides:
    LOAD_TEST_EMAIL       (default: loadtest@wanjala.local)
    LOAD_TEST_PASSWORD    (default: loadtest-dev-only-password)
    LOAD_TEST_WORKSPACE   (default: Load Test Workspace)

Usage::

    docker exec compose-web-1 python manage.py seed_load_test_user
    docker exec -e LOAD_TEST_PASSWORD=mysecret compose-web-1 python manage.py seed_load_test_user
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed dedicated user + workspace for load testing (idempotent)."

    def handle(self, *args, **options):
        from components.shared_platform.infrastructure.middleware.tenant_middlewares import (
            set_db_for_router,
        )
        from infrastructure.persistence.users.models import CustomUser
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceMembership,
            WorkspaceRole,
        )

        # Multi-tenant router reads from thread-local; in a management command
        # the middleware never ran, so the thread-local is unset and routing
        # is inconsistent across queries. Lock to the default DB for this seed.
        set_db_for_router("default")

        email = os.getenv("LOAD_TEST_EMAIL", "loadtest@wanjala.local")
        password = os.getenv("LOAD_TEST_PASSWORD", "loadtest-dev-only-password")
        workspace_name = os.getenv("LOAD_TEST_WORKSPACE", "Load Test Workspace")

        DB = "default"
        user, user_created = CustomUser.objects.using(DB).get_or_create(
            email=email,
            defaults={"username": email, "is_active": True, "is_verified": True},
        )
        # Always reset the password + verified flag so re-running fixes a stale local DB.
        user.set_password(password)
        user.is_active = True
        user.is_verified = True
        user.save(using=DB, update_fields=["password", "is_active", "is_verified"])

        # Use _base_manager — Workspace.objects is filtered to status="active",
        # so a fresh workspace (default status="inactive") would be invisible
        # to get_or_create on the next run and we'd create duplicates.
        workspace = (
            Workspace._base_manager.using(DB).filter(workspace_name=workspace_name).first()
        )
        ws_created = workspace is None
        if workspace is None:
            workspace = Workspace(
                workspace_name=workspace_name,
                workspace_owner=user,
                workspace_type=Workspace.TEAMSPACE,
                status="active",
            )
            workspace.save(using=DB)
        elif workspace.status != "active":
            # Recovery path for workspaces left "inactive" by an earlier run.
            workspace.status = "active"
            workspace.save(using=DB, update_fields=["status"])

        # Resolve the system 'owner' role — Phase 2 RBAC reads workspace_role
        # (capability bundle), not the legacy string field. A null workspace_role
        # is treated as "no permissions" and would 403 every endpoint that uses
        # has_workspace_permission(...). See ADR 0002.
        owner_role = (
            WorkspaceRole.objects.using(DB)
            .filter(slug="owner", is_system=True)
            .first()
        )
        if owner_role is None:
            self.stdout.write(self.style.WARNING(
                "  Could not find system role slug='owner' — has seed_system_roles run? "
                "RBAC checks will likely 403."
            ))

        membership, m_created = WorkspaceMembership.objects.using(DB).get_or_create(
            workspace=workspace,
            user=user,
            defaults={
                "role": WorkspaceMembership.Role.OWNER,
                "workspace_role": owner_role,
                "persona": WorkspaceMembership.Persona.ADMIN,
                "status": WorkspaceMembership.Status.ACTIVE,
            },
        )
        # Force role + workspace_role + status in case a previous seed left
        # any of them in a stale state (e.g. workspace_role=None from before
        # the capability-backed RBAC landed).
        owner_role_id = getattr(owner_role, "id", None)
        if (
            membership.role != WorkspaceMembership.Role.OWNER
            or membership.status != WorkspaceMembership.Status.ACTIVE
            or membership.workspace_role_id != owner_role_id
        ):
            membership.role = WorkspaceMembership.Role.OWNER
            membership.status = WorkspaceMembership.Status.ACTIVE
            membership.workspace_role = owner_role
            membership.save(using=DB, update_fields=["role", "status", "workspace_role"])

        self.stdout.write(self.style.SUCCESS("Load test seed ready:"))
        self.stdout.write(f"  user         = {email} ({'created' if user_created else 'updated'})")
        self.stdout.write(f"  password     = {password}")
        self.stdout.write(f"  workspace    = {workspace_name} ({'created' if ws_created else 'existing'}, status={workspace.status})")
        self.stdout.write(f"  workspace_id = {workspace.id}")
        self.stdout.write(
            f"  membership   = role={membership.role} workspace_role="
            f"{getattr(membership.workspace_role, 'slug', None)} persona={membership.persona} "
            f"({'created' if m_created else 'existing'})"
        )
        self.stdout.write("")
        self.stdout.write("Put these in tests/load/.env.load:")
        self.stdout.write(f"  LOAD_SMOKE_EMAIL={email}")
        self.stdout.write(f"  LOAD_SMOKE_PASSWORD={password}")
        self.stdout.write(f"  LOAD_SMOKE_WORKSPACE_ID={workspace.id}")
