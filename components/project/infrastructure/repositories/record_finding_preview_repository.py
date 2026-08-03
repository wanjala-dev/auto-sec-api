"""ORM adapter: stamp a proposed-fix preview onto a finding's board Task (ADR 0012 P6).

Implements :class:`RecordFindingPreviewPort` — the sole owner of the ``project.Task``
write for the integrations preview-before-commit flow, mirroring
``OrmRecordFindingDraftPrRepository`` (the draft-PR record). Preview grounds, it never
authorises (D2): this writes ``metadata.payload.proposed_patch`` + a provenance event +
a card comment, and NEVER touches ``draft_pr`` or opens a PR.

Contract:
- ``metadata.payload.proposed_patch`` = {path, code, language, change_summary,
  grounding, previewed_by, previewed_at}
- a growable ``metadata.provenance.events`` entry recording the preview (the AI action)
- ``last_handled_by`` / ``last_handled_at`` stamped on provenance
- a ``TaskComment`` describing the preview, authored by the requesting user

A finding that already carries a ``draft_pr`` is a no-op (nothing left to preview).
"""

from __future__ import annotations

from datetime import UTC, datetime

from components.project.application.ports.record_finding_preview_port import (
    RecordFindingPreviewCommand,
    RecordFindingPreviewPort,
    RecordFindingPreviewResult,
)


class OrmRecordFindingPreviewRepository(RecordFindingPreviewPort):
    def record_preview(self, *, command: RecordFindingPreviewCommand) -> RecordFindingPreviewResult:
        from infrastructure.persistence.project.models import Task, TaskComment
        from infrastructure.persistence.users.models import CustomUser

        task = Task.objects.filter(id=command.task_id, workspace_id=command.workspace_id).first()
        if task is None:  # deleted between the precondition check and now
            return RecordFindingPreviewResult(recorded=False)

        meta = task.metadata or {}
        payload = meta.get("payload") or {}
        if (payload.get("draft_pr") or {}).get("url"):
            # A PR already exists — preview is moot; don't overwrite provenance.
            return RecordFindingPreviewResult(recorded=False)

        previewed_at = datetime.now(UTC).isoformat()
        payload["proposed_patch"] = {
            "path": command.path,
            "code": command.code,
            "language": command.language,
            "change_summary": command.change_summary,
            "grounding": [dict(g) for g in command.grounding],
            "previewed_by": str(command.performed_by),
            "previewed_at": previewed_at,
        }
        meta["payload"] = payload

        # Same growable provenance shape the detector/triage/draft-PR pipeline appends
        # to — every AI action is stamped on the board.
        provenance = meta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        provenance["events"].append(
            {
                "actor": f"agent:{command.acting_agent} via user:{command.performed_by}",
                "action": f"previewed a proposed fix for {command.path}",
                "at": previewed_at,
            }
        )
        provenance["last_handled_by"] = command.acting_agent
        provenance["last_handled_at"] = previewed_at
        meta["provenance"] = provenance
        task.metadata = meta
        task.save(update_fields=["metadata", "updated_at"])

        author = CustomUser.objects.filter(id=command.performed_by).first()
        if author is not None:
            grounded_note = f" Grounded in {len(command.grounding)} prior vetted fix(es)." if command.grounding else ""
            TaskComment.objects.create(
                task=task,
                author=author,
                comment=(
                    f"🔍 Proposed-fix preview for `{command.path}`: "
                    f"{command.change_summary or 'minimal fix for this finding'}.{grounded_note} "
                    "Review before opening a draft PR — this is a preview, not a commit."
                ),
            )

        return RecordFindingPreviewResult(recorded=True)
