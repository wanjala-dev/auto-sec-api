"""Provision a tenant end-to-end — the tenancy skill §8 runbook as a command.

Until now the dedicated-tenant runbook lived only as skill prose plus the
acme/faura shell history: create the database, migrate it, insert the registry
row, seed the reference rows and the first admin + workspace inside a bound
``tenant_context``. Six hand-typed steps, each with a trap attached (a migrate
under the wrong router poisons ``django_migrations``; seeds outside the binding
land in the pool; a registry row before the seeds sends users to an empty
tenant). This command is those steps, in the safe order, idempotently.

Pooled tenant (a subdomain over the shared database):

    python manage.py provision_tenant senso --name "Senso"

Dedicated tenant (own database; the alias must ALREADY be present in
``TENANT_DATABASE_URLS`` so ``settings.DATABASES`` knows it — that is a
deploy-config action this process cannot do for itself):

    TENANT_ADMIN_PASSWORD=... python manage.py provision_tenant wanjala \\
        --name "Wanjala" --dedicated --create-db \\
        --admin-email admin@wanjala.test --workspace-name "Wanjala"

Order of operations (deliberate):

1. validate — subdomain shape, reserved list, no conflicting registry row;
2. (dedicated) ensure the database exists (``--create-db``; raw CREATE
   DATABASE — a management command is the one sanctioned home for schema SQL);
3. (dedicated) migrate that alias with the FINAL router configuration;
4. seed inside the tenant's binding — reference rows (subscription tiers,
   feature flags are tenant-routed apps, every database needs its own copy)
   and the first admin user + workspace;
5. registry row LAST — the host only starts resolving once the tenant behind
   it is fully built (fail-closed 404 until then, which is the point).

Idempotent throughout: a re-run after a partial failure repairs instead of
duplicating, and an existing admin's password is never rotated (the
``seed_demo_workspace`` discipline). The admin password comes from the
``TENANT_ADMIN_PASSWORD`` env var, never from argv (shell history) and never
from output (kubectl logs).
"""

from __future__ import annotations

import os
import re
from contextlib import nullcontext

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class Command(BaseCommand):
    help = "Provision a tenant (pooled by default; --dedicated for its own database) — registry, schema, seeds, admin."

    def add_arguments(self, parser):
        parser.add_argument("subdomain", help="Tenant label — 'wanjala' in wanjala.auto-sec.ai")
        parser.add_argument("--name", required=True, help="Display name (shown on the tenant's login screen)")
        parser.add_argument("--dedicated", action="store_true", help="Own database (default: pooled)")
        parser.add_argument(
            "--db-alias",
            default="",
            help="Dedicated connection alias (default: tenant_<subdomain>); must exist in TENANT_DATABASE_URLS",
        )
        parser.add_argument(
            "--create-db",
            action="store_true",
            help="CREATE DATABASE if missing (connects to --maintenance-db on the alias's server)",
        )
        parser.add_argument(
            "--maintenance-db",
            default="postgres",
            help="Database to connect to for CREATE DATABASE (default: postgres)",
        )
        parser.add_argument(
            "--admin-email", default="", help="Seed the first admin (password: TENANT_ADMIN_PASSWORD env)"
        )
        parser.add_argument("--workspace-name", default="", help="Seed the first workspace, owned by the admin")
        parser.add_argument("--skip-migrate", action="store_true", help="Skip migrating the dedicated database")
        parser.add_argument("--skip-seeds", action="store_true", help="Skip subscription-tier / feature-flag seeds")

    # ── entry point ─────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        from infrastructure.persistence.tenancy.models import RESERVED_SUBDOMAINS, Tenant

        subdomain = options["subdomain"].strip().lower()
        if not _SUBDOMAIN_RE.match(subdomain):
            raise CommandError(f"invalid subdomain {subdomain!r} — lowercase letters, digits and inner hyphens only")
        if subdomain in RESERVED_SUBDOMAINS:
            raise CommandError(f"{subdomain!r} is a reserved subdomain and can never be a tenant")

        name = options["name"].strip()
        if not name:
            raise CommandError("--name must not be blank — it is the tenant's login-screen identity")

        dedicated = options["dedicated"]
        alias = (options["db_alias"] or f"tenant_{subdomain}").strip() if dedicated else ""
        admin_email = options["admin_email"].strip().lower()
        workspace_name = options["workspace_name"].strip()
        if workspace_name and not admin_email:
            raise CommandError("--workspace-name needs --admin-email (a workspace must have an owner)")

        # A conflicting registry row means this subdomain is already a
        # DIFFERENT tenant — refuse rather than silently re-pointing a host.
        existing = Tenant.objects.filter(subdomain=subdomain).first()
        if existing and (
            existing.isolation_mode != ("dedicated" if dedicated else "pooled") or existing.db_alias != alias
        ):
            raise CommandError(
                f"subdomain {subdomain!r} already registered as {existing.isolation_mode}"
                f"{f' ({existing.db_alias})' if existing.db_alias else ''} — refusing to re-point it. "
                "Provision a different subdomain, or pass matching --dedicated/--db-alias to re-run idempotently."
            )

        if dedicated:
            self._require_alias(alias, subdomain)
            if options["create_db"]:
                self._ensure_database(alias, options["maintenance_db"])
            if not options["skip_migrate"]:
                self.stdout.write(self.style.NOTICE(f"migrating {alias} (final router config)"))
                call_command("migrate", database=alias, interactive=False, verbosity=options["verbosity"])

        binding = self._tenant_binding(dedicated, alias, subdomain)
        workspace_id = None
        with binding:
            if not options["skip_seeds"]:
                self.stdout.write(self.style.NOTICE("seeding reference rows (tiers, feature flags)"))
                call_command("seed_subscription_tiers", verbosity=options["verbosity"])
                call_command("seed_feature_flags", verbosity=options["verbosity"])
            if admin_email:
                admin = self._ensure_admin(admin_email)
                if workspace_name:
                    workspace_id = self._ensure_workspace(admin, workspace_name)

        row = self._ensure_registry_row(subdomain, name, dedicated, alias, workspace_id)

        self.stdout.write(self.style.SUCCESS(f"tenant {subdomain!r} provisioned ({row.isolation_mode})"))
        self.stdout.write(
            f"  login:      http://{subdomain}.auto-sec.ai  (local: add '127.0.0.1 {subdomain}.auto-sec.ai' to /etc/hosts)"
        )
        if admin_email:
            self.stdout.write(f"  admin:      {admin_email}")
        if workspace_id:
            self.stdout.write(f"  workspace:  {workspace_id} (pinned on the registry row)")

    # ── steps ───────────────────────────────────────────────────────────────

    def _require_alias(self, alias: str, subdomain: str) -> None:
        if alias in settings.DATABASES:
            return
        raise CommandError(
            f"connection alias {alias!r} is not in settings.DATABASES. Add it to the TENANT_DATABASE_URLS "
            f'env (JSON: {{"{alias}": "postgres://user:pw@host:5432/{alias}"}}) and restart the '
            "deployments (api, channels, celery workers) first — the alias must exist before this "
            "command can migrate or seed it. See the tenancy skill §8."
        )

    def _ensure_database(self, alias: str, maintenance_db: str) -> None:
        """CREATE DATABASE if missing, via the alias's own server credentials.

        Connects to *maintenance_db* on the alias's host because the target
        database may not exist yet — the same trick Django's test runner uses.
        Raw SQL is sanctioned here and only here (management command, schema
        operation).
        """
        import psycopg
        from psycopg import sql

        params = settings.DATABASES[alias]
        dbname = params["NAME"]
        conninfo = psycopg.conninfo.make_conninfo(
            dbname=maintenance_db,
            user=params.get("USER") or None,
            password=params.get("PASSWORD") or None,
            host=params.get("HOST") or None,
            port=params.get("PORT") or None,
        )
        with psycopg.connect(conninfo, autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
            if exists:
                self.stdout.write(f"database {dbname} already exists")
                return
            owner = params.get("USER") or "CURRENT_USER"
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(dbname), sql.Identifier(owner)))
            self.stdout.write(self.style.SUCCESS(f"created database {dbname} (owner {owner})"))

    @staticmethod
    def _tenant_binding(dedicated: bool, alias: str, subdomain: str):
        if not dedicated:
            # Pooled work runs under the ambient pooled binding manage.py set.
            return nullcontext()
        from components.shared_platform.infrastructure.tenancy.context import (
            KIND_DEDICATED,
            TenantContext,
            tenant_context,
        )

        return tenant_context(TenantContext(kind=KIND_DEDICATED, db_alias=alias, subdomain=subdomain))

    def _ensure_admin(self, email: str):
        """First admin, ``seed_demo_workspace`` discipline: password only at creation."""
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.filter(email=email).first()
        if user is not None:
            fixes = []
            if not user.is_verified:
                user.is_verified = True
                fixes.append("is_verified")
            if not user.is_active:
                user.is_active = True
                fixes.append("is_active")
            if fixes:
                user.save(update_fields=fixes)
                self.stdout.write(self.style.WARNING(f"repaired admin {email}: {', '.join(fixes)}"))
            return user

        password = os.environ.get("TENANT_ADMIN_PASSWORD", "")
        if not password:
            raise CommandError(
                f"admin {email} does not exist yet and TENANT_ADMIN_PASSWORD is not set. "
                "Pass the initial password via that env var (never via argv — shell history)."
            )
        user = CustomUser.objects.create(
            email=email,
            username=email.split("@", 1)[0],
            is_verified=True,
            is_active=True,
        )
        user.set_password(password)
        user.save(update_fields=["password"])
        self.stdout.write(self.style.SUCCESS(f"created admin {email}"))
        return user

    def _ensure_workspace(self, owner, workspace_name: str):
        from infrastructure.persistence.users.models import UserProfile
        from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

        # all_objects: the default manager filters status="active" — a
        # half-provisioned (or deactivated) workspace must be FOUND and
        # repaired, not duplicated.
        workspace = Workspace.objects.all_objects().filter(workspace_name=workspace_name, workspace_owner=owner).first()
        if workspace is None:
            workspace = Workspace.objects.create(
                workspace_name=workspace_name,
                workspace_type="teamspace",
                workspace_owner=owner,
                status="active",
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS(f"created workspace {workspace.id} ({workspace_name})"))
        else:
            fixes = []
            if workspace.status != "active":
                workspace.status = "active"
                fixes.append("status")
            if not workspace.is_active:
                workspace.is_active = True
                fixes.append("is_active")
            if fixes:
                workspace.save(update_fields=fixes)
                self.stdout.write(self.style.WARNING(f"repaired workspace {workspace.id}: {', '.join(fixes)}"))

        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=owner,
            defaults={"role": "owner", "persona": "admin", "status": "active"},
        )

        # The HUD resolves through the profile's active workspace — pin it only
        # when unset (never steal an existing admin's active workspace).
        profile, _ = UserProfile.objects.get_or_create(user=owner)
        if not profile.active_workspace_id:
            profile.active_workspace_id = workspace.id
            profile.save(update_fields=["active_workspace_id"])

        return workspace.id

    def _ensure_registry_row(self, subdomain: str, name: str, dedicated: bool, alias: str, workspace_id):
        """The registry row goes in LAST — the host resolves only once the tenant is built."""
        from infrastructure.persistence.tenancy.models import Tenant

        row = Tenant.objects.filter(subdomain=subdomain).first()
        if row is None:
            row = Tenant(
                subdomain=subdomain,
                name=name,
                isolation_mode="dedicated" if dedicated else "pooled",
                db_alias=alias,
                workspace_id=workspace_id,
                is_active=True,
            )
            row.full_clean()
            row.save()
            self.stdout.write(self.style.SUCCESS(f"registered tenant {subdomain!r} → {row.isolation_mode}"))
            return row

        fixes = []
        if row.name != name:
            row.name = name
            fixes.append("name")
        if workspace_id and row.workspace_id != workspace_id:
            row.workspace_id = workspace_id
            fixes.append("workspace_id")
        if not row.is_active:
            row.is_active = True
            fixes.append("is_active")
        if fixes:
            row.full_clean()
            row.save(update_fields=fixes)
            self.stdout.write(self.style.WARNING(f"repaired registry row: {', '.join(fixes)}"))
        return row
