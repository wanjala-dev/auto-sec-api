"""Trigger an Opengrep SAST scan of an allowlisted repo (ADR 0019).

    python manage.py scan_repo wanjala-dev/auto-sec-api --workspace <uuid>

Enqueues ``scanning.run_scan`` onto the ``code_security`` queue; the scanning worker
vends read access through the workspace's VcsConnection (allowlist fail-closed),
runs the OpengrepScanner through the configured ScanExecutionBackend (an ephemeral
K8s Job when SCAN_EXECUTION_BACKEND=k8s_job), and emits FindingObserved per finding
→ the findings SSOT. ``--sync`` runs it inline for a quick local proof.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Trigger an Opengrep code-security (SAST) scan of an allowlisted repo."

    def add_arguments(self, parser):
        parser.add_argument("repo", help="owner/repo to scan (must be on the VcsConnection allowlist)")
        parser.add_argument("--workspace", required=True, help="workspace UUID the scan belongs to")
        parser.add_argument("--connection", default=None, help="VcsConnection id (default: any allowlisting one)")
        parser.add_argument("--sync", action="store_true", help="run inline instead of enqueuing")

    def handle(self, *args, **opts):
        from components.code_security.application.use_cases.trigger_repo_scan_use_case import (
            RepoScanRejected,
            TriggerRepoScanUseCase,
        )
        from components.scanning.application.providers.scan_dispatch_provider import run_scan

        use_case = TriggerRepoScanUseCase()
        try:
            if opts["sync"]:
                prepared = use_case.prepare(
                    workspace_id=opts["workspace"], repo=opts["repo"], connection_id=opts["connection"]
                )
                result = run_scan(**prepared)
                self.stdout.write(self.style.SUCCESS(f"scan complete: {result}"))
            else:
                dispatched = use_case.execute(
                    workspace_id=opts["workspace"], repo=opts["repo"], connection_id=opts["connection"]
                )
                self.stdout.write(
                    self.style.SUCCESS(f"enqueued scan task={dispatched['task_id']} repo={dispatched['repo']}")
                )
        except RepoScanRejected as exc:
            raise CommandError(str(exc)) from exc
