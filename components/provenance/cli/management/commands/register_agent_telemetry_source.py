"""Register (or update) a workspace's agent-telemetry consent row.

The operator-side half of ADR 0023 P0: there is deliberately no self-serve REST
CRUD for this yet, because the row IS the consent boundary and the capability is
dark. An operator creates it with the customer, naming exactly the agents the
customer agreed to have observed.

    python manage.py register_agent_telemetry_source \\
        --workspace <uuid> --platform vercel --agents invoice-bot,refund-agent --activate

Fail-closed: without ``--agents`` the source ingests nothing. That is intentional
— an empty allowlist means "observe nothing", never "observe everything".
"""

from __future__ import annotations

from django.core.management import BaseCommand, CommandError

from infrastructure.persistence.provenance.models import AgentTelemetrySource


class Command(BaseCommand):
    help = "Register or update an AgentTelemetrySource (the agent-observation consent row)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", required=True, help="Workspace UUID.")
        parser.add_argument("--platform", required=True, help="Customer agent platform, e.g. 'vercel'.")
        parser.add_argument("--name", default="Agent telemetry", help="Human label for the source.")
        parser.add_argument(
            "--kind",
            default=AgentTelemetrySource.Kind.OTLP_JSON,
            choices=[choice[0] for choice in AgentTelemetrySource.Kind.choices],
            help="Capture mechanism; selects the AgentTelemetryPort adapter.",
        )
        parser.add_argument(
            "--agents",
            default="",
            help="Comma-separated agent ids the customer consents to have observed (the allowlist).",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Set status ACTIVE. Without it the source is created DRAFT and ingests nothing.",
        )

    def handle(self, *args, **options):
        allowlist = [entry.strip() for entry in (options["agents"] or "").split(",") if entry.strip()]
        status = AgentTelemetrySource.Status.ACTIVE if options["activate"] else AgentTelemetrySource.Status.DRAFT

        try:
            source, created = AgentTelemetrySource.objects.update_or_create(
                workspace_id=options["workspace"],
                platform=options["platform"].strip().lower(),
                kind=options["kind"],
                defaults={
                    "name": options["name"],
                    "agent_allowlist": allowlist,
                    "status": status,
                },
            )
        except Exception as exc:
            raise CommandError(f"Could not register the telemetry source: {exc}") from exc

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"  {verb} AgentTelemetrySource {source.id} ({status})"))
        self.stdout.write(
            f"  ingest URL path: /api/v1/provenance/workspaces/{options['workspace']}/agent-telemetry/{source.id}/ingest/"
        )
        if not allowlist:
            self.stdout.write(
                self.style.WARNING(
                    "  Allowlist is EMPTY — this source will ingest nothing. Pass --agents to consent to specific agents."
                )
            )
