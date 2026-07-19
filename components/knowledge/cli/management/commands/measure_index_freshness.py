"""Operator command: measure index freshness on demand.

Same logic as the ``audit_index_freshness`` Celery beat task — runs
the SLO measurement for every active workspace and reports the
compliance fraction. Two differences:

* The CLI version doesn't persist samples by default (``--persist``
  to opt in). One operator running the command to sanity-check the
  beat task shouldn't bloat the sample stream with extra rows.
* The CLI version prints per-workspace rows when ``--verbose`` is
  set, useful for spot-checking individual workspaces.

Usage::

    docker exec compose-web-1 python manage.py measure_index_freshness
    docker exec compose-web-1 python manage.py measure_index_freshness --verbose
    docker exec compose-web-1 python manage.py measure_index_freshness --persist
    docker exec compose-web-1 python manage.py measure_index_freshness --sla-target-seconds 300

See Tier 3 #14 in ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` for the
SLO definition and ``components/knowledge/infrastructure/tasks/
index_freshness_tasks.py`` for the beat-scheduled equivalent.
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Measure pgvector workspace-index freshness per the SLO. Prints a "
        "compliance summary and optionally persists per-workspace samples."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--persist",
            action="store_true",
            help=(
                "Write IndexFreshnessSample rows for each measured "
                "workspace. Default off — the beat task does the "
                "scheduled writes; this flag exists for one-off audits."
            ),
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print one line per workspace, not just the aggregate.",
        )
        parser.add_argument(
            "--sla-target-seconds",
            type=int,
            default=None,
            help=(
                "Override the default 600s SLA target. Useful for "
                "what-if comparisons — does NOT change the prod SLO."
            ),
        )

    def handle(self, *args, **options) -> None:
        from django.utils import timezone

        from components.knowledge.application.providers.index_freshness_provider import (
            measure_index_freshness,
        )
        from components.knowledge.application.use_cases.measure_index_freshness_use_case import (
            DEFAULT_SLA_TARGET_SECONDS,
        )
        from components.knowledge.infrastructure.tasks.index_freshness_tasks import (
            PASS_COMPLIANCE_TARGET,
        )
        from infrastructure.persistence.ai.aggregations.models import (
            IndexFreshnessSample,
        )
        from infrastructure.persistence.workspaces.models import Workspace

        persist = bool(options.get("persist"))
        verbose = bool(options.get("verbose"))
        sla_target_seconds = (
            options.get("sla_target_seconds") or DEFAULT_SLA_TARGET_SECONDS
        )

        use_case = measure_index_freshness()
        sample_time = timezone.now()

        queryset = (
            Workspace.objects.filter(is_active=True)
            .order_by("id")
            .values_list("id", "workspace_name")
        )

        samples_to_persist: list[IndexFreshnessSample] = []
        rows: list[tuple[str, str, int, bool]] = []  # (id, name, lag, ok)
        total = 0
        sla_met_count = 0
        failed = 0

        for workspace_id, workspace_name in queryset.iterator(
            chunk_size=500
        ):
            total += 1
            try:
                sample = use_case.execute(
                    workspace_id=str(workspace_id),
                    sample_time=sample_time,
                    sla_target_seconds=sla_target_seconds,
                )
            except Exception as exc:  # pylint: disable=broad-except
                failed += 1
                self.stderr.write(
                    self.style.WARNING(
                        f"measure failed for workspace_id={workspace_id}: {exc}"
                    )
                )
                continue

            if sample.sla_met:
                sla_met_count += 1
            rows.append(
                (
                    str(workspace_id),
                    workspace_name or "",
                    sample.lag_seconds,
                    sample.sla_met,
                )
            )
            if persist:
                samples_to_persist.append(
                    IndexFreshnessSample(
                        workspace_id=sample.workspace_id,
                        sample_time=sample.sample_time,
                        latest_event_time=sample.latest_event_time,
                        latest_index_time=sample.latest_index_time,
                        lag_seconds=sample.lag_seconds,
                        sla_target_seconds=sample.sla_target_seconds,
                        sla_met=sample.sla_met,
                    )
                )

        if persist and samples_to_persist:
            IndexFreshnessSample.objects.bulk_create(
                samples_to_persist, batch_size=500
            )

        compliance = sla_met_count / total if total else 1.0

        if verbose and rows:
            self.stdout.write("")
            self.stdout.write("Per-workspace freshness:")
            self.stdout.write(
                f"  {'workspace_id':<38} {'name':<30} {'lag':>10}  status"
            )
            self.stdout.write("  " + "-" * 90)
            for wid, name, lag, ok in rows:
                marker = "OK " if ok else "MISS"
                self.stdout.write(
                    f"  {wid:<38} {(name or '')[:30]:<30} "
                    f"{lag:>8}s  {marker}"
                )
            self.stdout.write("")

        self.stdout.write(
            f"workspaces measured: {total}  (failed: {failed})"
        )
        self.stdout.write(
            f"sla_met: {sla_met_count}/{total}  "
            f"(threshold: {sla_target_seconds}s)"
        )
        target_str = f"{PASS_COMPLIANCE_TARGET:.0%}"
        compliance_str = f"{compliance:.2%}"
        if compliance >= PASS_COMPLIANCE_TARGET:
            self.stdout.write(
                self.style.SUCCESS(
                    f"SLO compliance: {compliance_str} (target {target_str}) "
                    "— PASS"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"SLO compliance: {compliance_str} (target {target_str}) "
                    "— FAIL"
                )
            )
        if persist:
            self.stdout.write(
                f"persisted {len(samples_to_persist)} sample rows"
            )
