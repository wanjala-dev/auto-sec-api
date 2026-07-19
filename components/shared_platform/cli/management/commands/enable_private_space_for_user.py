"""Enable the private/personal workspace for a single user (opt-in pilot).

Idempotent. Safe to run repeatedly. For one user it:
1. Adds a USER-scoped ``feature.personal_space`` rule (enabled=True). The flag
   stays globally off in prod (GTM scope freeze); the user-scoped rule wins via
   the resolver order ``user -> workspace -> global -> default``.
2. Provisions the user's private (personal-type) workspace if they don't already
   have one — needed because already-onboarded users never had one auto-minted.

This is the per-user step of the Notion-style "Private + Teamspaces" pilot. The
provisioning core (``ensure_personal_workspace``) is the same logic the
onboarding bootstrap will call once private spaces auto-provision for everyone.

Usage::

    docker exec compose-web-1 python manage.py enable_private_space_for_user c0d3henry@gmail.com
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Enable + provision a private/personal workspace for one user (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email of the user to enable private space for.")

    def handle(self, *args, **options):
        from components.shared_platform.infrastructure.middleware.tenant_middlewares import (
            set_db_for_router,
        )
        from components.identity.infrastructure.adapters.workspace_bootstrap import (
            ensure_personal_workspace,
        )
        from components.shared_platform.infrastructure.services.feature_flags import (
            bump_feature_flags_version,
        )
        from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
        from infrastructure.persistence.users.models import CustomUser

        # Management commands don't run tenant middleware, so the router's
        # thread-local is unset. Lock to default for consistent routing.
        set_db_for_router("default")

        email = options["email"].strip()
        user = CustomUser.objects.filter(email__iexact=email).first()
        if not user:
            raise CommandError(f"No user found with email {email!r}.")

        flag, _ = FeatureFlag.objects.get_or_create(
            key="feature.personal_space",
            defaults={
                "default_enabled": True,
                "description": "Private/personal workspace (per-user opt-in).",
            },
        )
        rule, created = FeatureFlagRule.objects.update_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.USER,
            user=user,
            defaults={"enabled": True, "note": "Private-space pilot opt-in"},
        )
        bump_feature_flags_version()
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} user-scoped personal_space rule "
                f"for {email} (user_id={user.id})."
            )
        )

        workspace = ensure_personal_workspace(user)
        if workspace is None:
            raise CommandError(
                "Could not provision the private workspace — the 'personal' sector "
                "is missing. Seed sectors first (e.g. configure_site / seed sectors)."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Private workspace ready: {workspace.workspace_name!r} "
                f"(id={workspace.id}, type={workspace.workspace_type}, privacy={workspace.privacy})."
            )
        )
