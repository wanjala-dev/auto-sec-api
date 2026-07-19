"""Mint the email-verification token for a QA E2E account.

The registration flow emails the user a link of the form
``<frontend>/EmailConfirmed/?token=<jwt>`` where the token is simply
``RefreshToken.for_user(user).access_token`` (see
``components/identity/api/controller.py::RegisterView``). In an automated
E2E run there is no inbox to read, so this command mints the exact same
token the email would have carried and prints it as JSON. The test then
drives the REAL frontend confirm page + ``/identity/email-verify/``
endpoint — automation replaces reading the email, never the product path.

Guard rails: refuses to run unless ``settings.DEBUG`` is true or the
operator explicitly sets ``QA_E2E_ALLOW=1`` in the environment, and only
serves accounts on the dedicated QA domain (``@qa.octopi.dev`` by
default) so it can never become a verification bypass for real users.

Usage:
    python manage.py qa_email_token --email qa-admin-x1@qa.octopi.dev
"""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management import BaseCommand, CommandError

QA_DOMAIN = "qa.octopi.dev"


def qa_commands_allowed() -> bool:
    """QA lifecycle commands run on dev/test stacks only (or explicit opt-in)."""
    return bool(getattr(settings, "DEBUG", False)) or os.environ.get("QA_E2E_ALLOW") == "1"


class Command(BaseCommand):
    help = "Print the email-verification token for a *@qa.octopi.dev account (E2E harness glue)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="QA account email (must be on the QA domain).")
        parser.add_argument(
            "--domain",
            default=QA_DOMAIN,
            help=f"Allowed email domain (default: {QA_DOMAIN}).",
        )

    def handle(self, *args, **options):
        if not qa_commands_allowed():
            raise CommandError("qa_email_token is disabled outside DEBUG (set QA_E2E_ALLOW=1 to override).")

        from rest_framework_simplejwt.tokens import RefreshToken

        from infrastructure.persistence.users.models import CustomUser

        email = options["email"].strip().lower()
        domain = options["domain"].strip().lower()
        if not email.endswith(f"@{domain}"):
            raise CommandError(f"refusing: {email} is not on the QA domain @{domain}")

        user = CustomUser.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"no user with email {email}")

        token = str(RefreshToken.for_user(user).access_token)
        confirm_path = getattr(settings, "EMAIL_CONFIRMATION_REDIRECT_PATH", "/EmailConfirmed/")
        self.stdout.write(
            json.dumps(
                {
                    "email": user.email,
                    "is_verified": user.is_verified,
                    "token": token,
                    "confirm_path": f"{confirm_path}?token={token}",
                }
            )
        )
