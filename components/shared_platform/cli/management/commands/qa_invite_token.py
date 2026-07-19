"""Print the pending persona-invitation token for a QA E2E invitee.

The persona invite flow emails a magic link ``/invite/accept?token=<hex>``
whose token is stored in plaintext on ``team.Invitation.token``. In an
automated E2E run there is no inbox to read, so this command looks up the
latest pending invitation for the given email and prints its token as
JSON. The test then drives the REAL ``/invite/accept`` page (info fetch,
new-user password form, accept POST) — automation replaces reading the
email, never the product path.

Same guard rails as ``qa_email_token``: DEBUG-only (or QA_E2E_ALLOW=1)
and locked to the dedicated QA email domain.

Usage:
    python manage.py qa_invite_token --email qa-sponsor-x1@qa.octopi.dev
    python manage.py qa_invite_token --email ... --workspace-id <uuid>
"""

from __future__ import annotations

import json

from django.core.management import BaseCommand, CommandError

from components.shared_platform.cli.management.commands.qa_email_token import QA_DOMAIN, qa_commands_allowed


class Command(BaseCommand):
    help = "Print the pending invitation token for a *@qa.octopi.dev invitee (E2E harness glue)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Invitee email (must be on the QA domain).")
        parser.add_argument("--workspace-id", default=None, help="Optional workspace UUID to disambiguate.")
        parser.add_argument(
            "--domain",
            default=QA_DOMAIN,
            help=f"Allowed email domain (default: {QA_DOMAIN}).",
        )

    def handle(self, *args, **options):
        if not qa_commands_allowed():
            raise CommandError("qa_invite_token is disabled outside DEBUG (set QA_E2E_ALLOW=1 to override).")

        from infrastructure.persistence.team.models import Invitation

        email = options["email"].strip().lower()
        domain = options["domain"].strip().lower()
        if not email.endswith(f"@{domain}"):
            raise CommandError(f"refusing: {email} is not on the QA domain @{domain}")

        qs = Invitation.objects.filter(email__iexact=email, status=Invitation.INVITED).exclude(token="")
        if options["workspace_id"]:
            qs = qs.filter(workspace_id=options["workspace_id"])
        invitation = qs.order_by("-date_sent").first()
        if invitation is None:
            raise CommandError(f"no pending invitation with a token for {email}")

        self.stdout.write(
            json.dumps(
                {
                    "email": invitation.email,
                    "workspace_id": str(invitation.workspace_id),
                    "persona": invitation.persona,
                    "role": invitation.role,
                    "token": invitation.token,
                    "accept_path": f"/invite/accept?token={invitation.token}",
                }
            )
        )
