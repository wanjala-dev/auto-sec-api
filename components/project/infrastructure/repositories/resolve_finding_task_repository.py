"""ORM adapter: mark a finding board-task resolved (ADR 0012 P4a).

Implements :class:`ResolveFindingTaskPort`. The project context owns the board
``Task``, so THIS is the sanctioned place the finding-resolved transition is
written — other contexts route here rather than mutating the Task themselves
(architecture skill C2). The write mirrors the finding pipeline's own metadata
conventions (``metadata.triage.status`` + a growable ``metadata.provenance``
trail, the same shape ``_finding_processing`` / ``open_draft_pr`` append to), so
the ``remediation`` entry-gate's ``BoardFindingFactsRepository`` reads it back as
``finding_resolved=True`` uniformly.

Idempotent + concurrency-safe: the resolved marker is set under a row lock, after
re-reading status, so two overlapping reconciler cycles never double-write or
double-emit. Best-effort ``FindingResolved`` emission (after commit) lets other
lenses react; a publish hiccup never fails the resolve.
"""

from __future__ import annotations

import logging

from components.project.application.ports.resolve_finding_task_port import (
    ResolveFindingTaskCommand,
    ResolveFindingTaskPort,
    ResolveFindingTaskResult,
)

logger = logging.getLogger(__name__)


def _is_resolved(metadata: dict) -> bool:
    triage = metadata.get("triage") or {}
    if str(triage.get("status", "")).lower() == "resolved":
        return True
    payload = metadata.get("payload") or {}
    return bool(payload.get("resolved"))


class OrmResolveFindingTaskRepository(ResolveFindingTaskPort):
    def resolve_finding_task(self, *, command: ResolveFindingTaskCommand) -> ResolveFindingTaskResult:
        from datetime import UTC, datetime

        from django.db import transaction

        from infrastructure.persistence.project.models import Task

        try:
            with transaction.atomic():
                task = (
                    Task.objects.select_for_update()
                    .filter(id=command.task_id, workspace_id=command.workspace_id)
                    .first()
                )
                if task is None:
                    # Absent OR another workspace's task — never leak/mutate across
                    # the tenant boundary.
                    return ResolveFindingTaskResult(
                        task_id=command.task_id, resolved=False, already_resolved=False, found=False
                    )

                meta = task.metadata or {}
                if _is_resolved(meta):
                    return ResolveFindingTaskResult(
                        task_id=str(task.id), resolved=True, already_resolved=True, found=True
                    )

                resolved_at = datetime.now(UTC).isoformat()
                triage = dict(meta.get("triage") or {})
                triage["status"] = "resolved"
                triage["resolved_at"] = resolved_at
                triage["resolved_reason"] = command.reason
                meta["triage"] = triage
                # Also stamp the payload flag the facts reader accepts, so either
                # read path sees resolution.
                payload = dict(meta.get("payload") or {})
                payload["resolved"] = True
                meta["payload"] = payload

                provenance = meta.get("provenance") or {"events": []}
                provenance.setdefault("events", [])
                actor = command.resolved_by or "system:remediation_reconciler"
                provenance["events"].append(
                    {
                        "actor": actor,
                        "action": f"resolved finding ({command.reason})",
                        "at": resolved_at,
                    }
                )
                provenance["last_handled_by"] = actor
                provenance["last_handled_at"] = resolved_at
                meta["provenance"] = provenance

                task.metadata = meta
                task.save(update_fields=["metadata", "updated_at"])

                fingerprint = str(payload.get("fingerprint") or meta.get("fingerprint") or "")
                workspace_id = str(task.workspace_id)

            # Dispatch AFTER commit — the resolve is the fact, the event is a
            # side-effect other lenses may act on. A publish failure is logged, not
            # raised (the finding is resolved regardless).
            self._emit_finding_resolved(
                workspace_id=workspace_id,
                fingerprint=fingerprint,
                reason=command.reason,
            )
            logger.info(
                "finding_task_resolved workspace_id=%s task_id=%s reason=%s",
                command.workspace_id,
                command.task_id,
                command.reason,
            )
            return ResolveFindingTaskResult(task_id=command.task_id, resolved=True, already_resolved=False, found=True)
        except Exception:
            # A resolve failure must surface (never a silent swallow); the reconciler
            # logs + continues to the next candidate. Re-raise with traceback.
            logger.exception(
                "finding_task_resolve_failed workspace_id=%s task_id=%s",
                command.workspace_id,
                command.task_id,
            )
            raise

    @staticmethod
    def _emit_finding_resolved(*, workspace_id: str, fingerprint: str, reason: str) -> None:
        """Best-effort ``FindingResolved`` emission for cross-lens reaction.

        The board Task is not the CNAPP Finding SSOT (it has no finding UUID/fingerprint
        of its own for a log-watch card), so we only emit when the finding carries a
        real ``fingerprint`` — deriving a stable finding UUID from ``(workspace, fingerprint)``
        so the event is deterministic and JSON-safe. When there's no fingerprint we skip
        (log), rather than fabricate an identity — honesty over a dead event.
        """
        if not fingerprint:
            logger.info("finding_resolved_event_skipped workspace_id=%s reason=no_fingerprint", workspace_id)
            return
        try:
            import uuid

            from components.shared_kernel.domain.events import FindingResolved
            from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
                CeleryEventPublisher,
            )

            ws_uuid = uuid.UUID(workspace_id)
            finding_uuid = uuid.uuid5(ws_uuid, fingerprint)
            CeleryEventPublisher().publish(
                FindingResolved(
                    workspace_id=ws_uuid,
                    finding_id=finding_uuid,
                    fingerprint=fingerprint,
                    reason=reason,
                )
            )
        except Exception:
            logger.exception("finding_resolved_event_publish_failed workspace_id=%s", workspace_id)
