"""ORM adapter: stamp a draft-PR outcome onto a finding's board Task.

Implements :class:`RecordFindingDraftPrPort`. This is the sole owner of the
``project.Task`` write for the integrations draft-PR flow — the logic is the
verbatim behaviour that previously lived inline in
``open_draft_pr_use_case._record_on_finding``, moved to the owning context so
integrations never touches ``project``'s models (architecture-skill C2).

Contract preserved exactly:
- ``metadata.payload.draft_pr`` = {url, repo, branch, opened_by, opened_at}
- a growable ``metadata.provenance.events`` entry recording the acting agent
- ``last_handled_by`` / ``last_handled_at`` stamped on provenance
- a ``TaskComment`` linking the PR, authored by the approving user

Re-checks ``draft_pr`` right before writing so a concurrent open (two operators
clicking at once) keeps the first PR's record.
"""

from __future__ import annotations

from datetime import UTC, datetime

from components.project.application.ports.record_finding_draft_pr_port import (
    RecordFindingDraftPrCommand,
    RecordFindingDraftPrPort,
    RecordFindingDraftPrResult,
    get_draft_pr,
    set_draft_pr,
)


class OrmRecordFindingDraftPrRepository(RecordFindingDraftPrPort):
    def record_draft_pr(self, *, command: RecordFindingDraftPrCommand) -> RecordFindingDraftPrResult:
        from infrastructure.persistence.project.models import Task, TaskComment
        from infrastructure.persistence.users.models import CustomUser

        task = Task.objects.filter(id=command.task_id, workspace_id=command.workspace_id).first()
        if task is None:  # deleted between the precondition check and now
            return RecordFindingDraftPrResult(recorded=False)

        meta = task.metadata or {}
        if get_draft_pr(meta).get("url"):
            return RecordFindingDraftPrResult(recorded=False)

        opened_at = datetime.now(UTC).isoformat()
        # Written through the canonical accessor so readers filtering on the
        # same path (the remediation reconciler) can never drift from the shape.
        set_draft_pr(
            meta,
            {
                "url": command.pr_url,
                "repo": command.pr_repo,
                "branch": command.branch,
                "opened_by": str(command.performed_by),
                "opened_at": opened_at,
            },
        )

        # Same growable provenance shape the detector/triage pipeline appends to.
        provenance = meta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        provenance["events"].append(
            {
                "actor": f"agent:{command.acting_agent} via user:{command.performed_by}",
                "action": f"opened draft PR {command.pr_url}",
                "at": opened_at,
            }
        )
        provenance["last_handled_by"] = command.acting_agent
        provenance["last_handled_at"] = opened_at
        meta["provenance"] = provenance
        task.metadata = meta
        task.save(update_fields=["metadata", "updated_at"])

        author = CustomUser.objects.filter(id=command.performed_by).first()
        if author is not None:
            TaskComment.objects.create(
                task=task,
                author=author,
                comment=(
                    f"🔧 Draft PR opened for this finding: {command.pr_url} "
                    f"(branch `{command.branch}`, repo `{command.pr_repo}`)."
                ),
            )

        return RecordFindingDraftPrResult(recorded=True)
