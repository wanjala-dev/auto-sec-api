"""Bootstrap a fresh dev environment from env vars.

Runs on every ``docker compose up`` — fully idempotent. Creates:
1. Superuser (from SUPER_USER_PASSWORD)
2. Workspace defaults (categories, plans, contribution means)
3. Default workspace (if PERSONA_WORKSPACE_NAME is set)
4. Persona test users (if PERSONA_PASSWORD is set)
5. Payment test data (if personas are created)

Env vars (all optional — skip steps when unset):

    SUPER_USER_PASSWORD=changeme
    PERSONA_WORKSPACE_NAME=Wanjala Foundation    # creates workspace if missing
    PERSONA_PASSWORD=testpass123                  # triggers persona creation
    PERSONA_EMAIL_DOMAIN=test.octopi.dev          # default: test.octopi.dev
    PERSONA_ADMIN_EMAIL=admin@test.octopi.dev
    PERSONA_CONTRIBUTOR_EMAIL=contributor@test.octopi.dev
    PERSONA_SPONSOR_EMAIL=sponsor@test.octopi.dev
    PERSONA_PERSONAL_EMAIL=personal@test.octopi.dev
"""

from __future__ import annotations

import os

from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = "Bootstrap dev environment: superuser + workspace defaults + persona users (idempotent, env-driven)."

    def handle(self, *args, **options):
        self._step_superuser()
        self._step_workspace_defaults()
        self._step_ai_models()
        workspace_id = self._step_ensure_workspace()
        if workspace_id:
            self._step_payment_data(workspace_id)
            self._step_personas(workspace_id)

    def _step_ai_models(self):
        self.stdout.write(self.style.NOTICE("Seeding AI model catalog..."))
        try:
            call_command("seed_ai_models", "--available", verbosity=0)
            self.stdout.write(self.style.SUCCESS("  AI models ready"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  AI model seed skipped: {e}"))

    def _step_superuser(self):
        password = os.getenv("SUPER_USER_PASSWORD")
        if not password:
            self.stdout.write("  SUPER_USER_PASSWORD not set — skipping superuser")
            return
        self.stdout.write(self.style.NOTICE("Creating superuser..."))
        call_command("create_superuser", verbosity=0)
        self.stdout.write(self.style.SUCCESS("  Superuser ready"))

    def _step_workspace_defaults(self):
        self.stdout.write(self.style.NOTICE("Bootstrapping workspace defaults..."))
        call_command("bootstrap_workspace_defaults", verbosity=0)
        self.stdout.write(self.style.SUCCESS("  Workspace defaults ready"))

    def _step_ensure_workspace(self) -> str | None:
        workspace_name = os.getenv("PERSONA_WORKSPACE_NAME")
        if not workspace_name and not os.getenv("PERSONA_PASSWORD"):
            self.stdout.write("  PERSONA_WORKSPACE_NAME not set — skipping workspace + personas")
            return None

        from infrastructure.persistence.workspaces.models import Workspace

        # Find existing workspace by name, or use the first teamspace
        workspace = None
        if workspace_name:
            workspace = Workspace.objects.filter(workspace_name__iexact=workspace_name).first()

        if not workspace:
            workspace = Workspace.objects.filter(workspace_type="teamspace").first()

        if not workspace:
            self.stdout.write(self.style.WARNING("  No teamspace found — skipping personas"))
            return None

        self.stdout.write(f"  Using workspace: {workspace.workspace_name} ({workspace.id})")
        return str(workspace.id)

    def _step_payment_data(self, workspace_id: str):
        self.stdout.write(self.style.NOTICE("Seeding payment test data..."))
        try:
            call_command("seed_payment_test_data", workspace_id=workspace_id, verbosity=0)
            self.stdout.write(self.style.SUCCESS("  Payment data ready"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Payment seed skipped: {e}"))

    def _step_personas(self, workspace_id: str):
        password = os.getenv("PERSONA_PASSWORD")
        if not password:
            self.stdout.write("  PERSONA_PASSWORD not set — skipping persona users")
            return

        domain = os.getenv("PERSONA_EMAIL_DOMAIN", "test.octopi.dev")
        self.stdout.write(self.style.NOTICE("Creating persona users..."))
        try:
            call_command(
                "seed_personas",
                workspace_id=workspace_id,
                password=password,
                email_domain=domain,
                verbosity=0,
            )
            self.stdout.write(self.style.SUCCESS(
                f"  Personas ready (password: {password})\n"
                f"    admin@{domain}\n"
                f"    contributor@{domain}\n"
                f"    sponsor@{domain}\n"
                f"    personal@{domain}"
            ))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Persona seed skipped: {e}"))
