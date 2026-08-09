"""Re-point findings stranded on a non-specialist ``agent_type`` so triage can see them.

The strand: a routable finding card stamped with a NON-specialist ``agent_type``
(``ai_teammate`` and friends) is skipped by the finding router forever. The card
looks normal on the board, no error is raised anywhere, and the finding simply never
gets a fix. 15 ``ai.code_security`` cards sat like that until they were spotted by
hand; ``test_every_routable_board_source_names_a_real_specialist`` now makes the
class impossible to reintroduce at build time, and THIS repairs rows already written
by the code that had the bug.

Idempotent and conservative:
* only touches cards whose ``source_type`` is routable AND whose ``agent_type`` is a
  non-specialist — a correctly-routed card is never rewritten;
* never re-opens a finished finding: cards already stamped ``triage.status=triaged``
  are left alone (their fix exists; re-pointing them would re-queue settled work);
* the target specialist is read from the SAME source→board mapping the live pipeline
  uses, so this can never invent a routing the product does not have;
* ``--dry-run`` prints the plan and writes nothing.

Usage::

    python manage.py backfill_stranded_findings --dry-run
    python manage.py backfill_stranded_findings
    python manage.py backfill_stranded_findings --workspace <uuid>
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from components.agents.application.handlers.finding_raised_board_handler import _SOURCE_BOARD
from components.shared_kernel.domain.triage import (
    NON_SPECIALIST_AGENT_TYPES,
    ROUTABLE_SOURCE_TYPES,
)

logger = logging.getLogger(__name__)


def _specialist_by_source_type() -> dict[str, str]:
    """``{source_type: specialist}`` for routable sources, read off the live mapping.

    Derived from ``_SOURCE_BOARD`` (the one place a source declares its routing
    target) rather than a second hand-written table — a hand-maintained copy is the
    same drift trap that produced the strand in the first place.
    """
    out: dict[str, str] = {}
    for mapping in _SOURCE_BOARD.values():
        source_type = mapping.get("source_type", "")
        if source_type not in ROUTABLE_SOURCE_TYPES:
            continue
        target = (mapping.get("default_agent_type") or "").strip()
        if target and target not in NON_SPECIALIST_AGENT_TYPES:
            out[source_type] = target
    # Sources whose builder hard-codes the specialist (no `default_agent_type`
    # override needed) — kept explicit so the repair never guesses.
    out.setdefault("ai.code_security", "code_security_agent")
    out.setdefault("ai.cloud_exposure", "triage_agent")
    out.setdefault("ai.container_security", "triage_agent")
    return out


class Command(BaseCommand):
    help = "Re-point routable findings stranded on a non-specialist agent_type."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", dest="workspace_id", default=None, help="Limit to one workspace.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")

    def handle(self, *args, **options):
        from infrastructure.persistence.project.models import Task

        targets = _specialist_by_source_type()
        qs = Task.objects.filter(source_type__in=list(targets)).only("id", "source_type", "metadata")
        if options.get("workspace_id"):
            qs = qs.filter(workspace_id=options["workspace_id"])

        planned: list[tuple[object, str, str, str]] = []
        for task in qs.iterator(chunk_size=500):
            meta = task.metadata or {}
            current = str(meta.get("agent_type") or "").strip()
            if current not in NON_SPECIALIST_AGENT_TYPES:
                continue  # correctly routed already
            if (meta.get("triage") or {}).get("status") == "triaged":
                continue  # settled — never re-queue a finding that already has its fix
            target = targets.get(task.source_type or "")
            if not target:
                continue
            planned.append((task.id, task.source_type, current or "(empty)", target))

        if not planned:
            self.stdout.write(self.style.SUCCESS("No stranded findings — nothing to repair."))
            return

        for task_id, source_type, current, target in planned:
            self.stdout.write(f"  {task_id}  {source_type}  {current} → {target}")

        if options.get("dry_run"):
            self.stdout.write(self.style.WARNING(f"DRY RUN — {len(planned)} finding(s) would be re-pointed."))
            return

        at = timezone.now().isoformat()
        repaired = 0
        for task_id, _source_type, current, target in planned:
            try:
                with transaction.atomic():
                    # Row-locked + re-checked, same discipline as the triage write, so
                    # a concurrent specialist run can never be clobbered.
                    locked = Task.objects.select_for_update(of=("self",)).filter(id=task_id).first()
                    if locked is None:
                        continue
                    meta = locked.metadata or {}
                    if str(meta.get("agent_type") or "").strip() not in NON_SPECIALIST_AGENT_TYPES:
                        continue
                    if (meta.get("triage") or {}).get("status") == "triaged":
                        continue
                    meta["agent_type"] = target
                    provenance = meta.get("provenance") or {"events": []}
                    provenance.setdefault("events", [])
                    provenance["events"].append(
                        {
                            "actor": "system:backfill_stranded_findings",
                            "action": f"re-pointed from '{current}' to '{target}' so triage can reach it",
                            "at": at,
                        }
                    )
                    meta["provenance"] = provenance
                    locked.metadata = meta
                    locked.save(update_fields=["metadata", "updated_at"])
                    repaired += 1
            except Exception:
                logger.exception("backfill_stranded_findings failed task_id=%s", task_id)

        self.stdout.write(self.style.SUCCESS(f"Re-pointed {repaired} stranded finding(s)."))
        self.stdout.write("They will be picked up by the next router pass (≤5 min), or immediately on the next scan.")
