"""Trigger a Trivy container-image scan (ADR 0006).

    python manage.py scan_image python:3.9-slim --workspace <uuid>

Enqueues ``scanning.run_scan`` onto the ``container_security`` queue; the scanning
worker resolves the TrivyScanner, runs it through the configured ScanExecutionBackend
(an ephemeral K8s Job when SCAN_EXECUTION_BACKEND=k8s_job), and emits FindingObserved
per vulnerability → the findings SSOT. ``--sync`` runs it inline for a quick local proof.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

_SOURCE = "container_security.trivy"


class Command(BaseCommand):
    help = "Trigger a Trivy container-image vulnerability scan."

    def add_arguments(self, parser):
        parser.add_argument("image", help="container image reference, e.g. python:3.9-slim")
        parser.add_argument("--workspace", required=True, help="workspace UUID the scan belongs to")
        parser.add_argument("--connection", default=None, help="AWS connection id (for ECR image pulls)")
        parser.add_argument("--account", default="", help="AWS account id (for ECR)")
        parser.add_argument("--sync", action="store_true", help="run inline instead of enqueuing")

    def handle(self, *args, **opts):
        from components.scanning.infrastructure.tasks.scan_tasks import dispatch_scan, run_scan

        kwargs = dict(
            source=_SOURCE,
            workspace_id=opts["workspace"],
            target_ref=opts["image"],
            connection_id=opts["connection"],
            account_id=opts["account"],
        )
        if opts["sync"]:
            result = run_scan(**kwargs)
            self.stdout.write(self.style.SUCCESS(f"scan complete: {result}"))
        else:
            async_result = dispatch_scan(**kwargs)
            self.stdout.write(self.style.SUCCESS(f"enqueued scan task={async_result.id} image={opts['image']}"))
