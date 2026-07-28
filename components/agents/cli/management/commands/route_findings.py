"""Management command: route a workspace's pending board findings to their triage
specialists on demand.

A CLI **driving adapter**. Findings land on the SOC board carrying a source_type + a
declared specialist (e.g. an attack-path finding → the triage agent), but the
``AiFindingRouterDetector`` only dispatches them to that specialist on the scheduled
AI-teammate cycle. This runs the router NOW for one workspace, so pending attack-path /
cloud-exposure / logwatch / container findings get triaged without waiting for (or
enabling) the full cycle. The dispatch is async — the specialist's deep run happens on
the ai-teammate worker; this just enqueues it.

Thin: build the detector context, run the router, report (Rule 4 — primary adapters are
thin). Same router the scheduled cycle drives.
"""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Dispatch a workspace's pending board findings to their triage specialists (on demand)."

    def add_arguments(self, parser):
        parser.add_argument("workspace_id", help="The workspace UUID whose pending findings to route.")

    def handle(self, *args, **options):
        try:
            workspace_id = UUID(str(options["workspace_id"]))
        except (ValueError, TypeError) as exc:
            raise CommandError(f"Invalid workspace_id: {options['workspace_id']!r}") from exc

        from components.agents.domain.detectors.base import DetectorContext
        from components.agents.infrastructure.adapters.actions.detectors.logwatch import (
            AiFindingRouterDetector,
        )
        from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
            not_triaged_filter,
        )
        from infrastructure.persistence.project.models import Task

        routable = AiFindingRouterDetector.ROUTABLE_SOURCE_TYPES
        pending = (
            Task.objects.filter(workspace_id=workspace_id, source_type__in=routable)
            .filter(not_triaged_filter())
            .count()
        )

        # The router enqueues the specialist deep run via transaction.on_commit (dispatch
        # after commit — celery-tasks §0). Wrap in an explicit atomic() so that commit
        # actually happens (and the on_commit hook fires) before this command exits; without
        # a committed transaction the deferred dispatch is silently discarded.
        from django.db import transaction

        with transaction.atomic():
            AiFindingRouterDetector().execute(
                DetectorContext(
                    workspace_id=str(workspace_id),
                    teammate_id="",
                    run_at=timezone.now(),
                    last_run_at=None,
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"routed pending findings workspace={workspace_id} pending={pending} "
                f"(dispatched to specialists; the deep triage runs on the ai-teammate worker)"
            )
        )
