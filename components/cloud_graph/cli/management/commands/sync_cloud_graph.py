"""Management command: sync the cloud asset graph for a workspace on demand.

A CLI **driving adapter**. The asset graph + attack paths otherwise refresh only on the
scheduled AI-teammate detector cycle (every 5 min, alongside every other detector). This
runs the same two use cases NOW for one workspace — derive ``CloudAsset`` rows from the
Finding SSOT (Prowler-derived), then materialize the ranked attack paths — so an operator
can light up the graph right after connecting an account and scanning, without waiting for
the cycle or paying for the agent delegations it also triggers.

Thin: parse args, call the use cases, report. No business logic here (Rule 4 — primary
adapters are thin). The use cases are the same ones the ``cloud_graph.sync`` and
``cloud_graph.attack_paths`` detectors drive.
"""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider


class Command(BaseCommand):
    help = "Sync the cloud asset graph + materialize attack paths for a workspace (on demand)."

    def add_arguments(self, parser):
        parser.add_argument("workspace_id", help="The workspace UUID whose graph to sync.")

    def handle(self, *args, **options):
        try:
            workspace_id = UUID(str(options["workspace_id"]))
        except (ValueError, TypeError) as exc:
            raise CommandError(f"Invalid workspace_id: {options['workspace_id']!r}") from exc

        sync = CloudGraphProvider.build_sync_cloud_assets_use_case().execute(workspace_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"cloud_graph synced workspace={workspace_id} "
                f"assets_upserted={sync.assets_upserted} edges_upserted={sync.edges_upserted} "
                f"findings_scanned={sync.findings_scanned}"
            )
        )

        paths = CloudGraphProvider.build_materialize_attack_paths_use_case().execute(workspace_id, timezone.now())
        self.stdout.write(
            self.style.SUCCESS(f"attack_paths materialized workspace={workspace_id} paths_found={paths.paths_found}")
        )
