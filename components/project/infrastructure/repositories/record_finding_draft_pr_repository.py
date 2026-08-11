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
    AttachDraftPrPatchCommand,
    AttachDraftPrPatchResult,
    MarkDraftPrRejectedCommand,
    MarkDraftPrRejectedResult,
    RecordFindingDraftPrCommand,
    RecordFindingDraftPrPort,
    RecordFindingDraftPrResult,
    bound_diff,
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
                "verification": command.verification,
                "verification_gap": command.verification_gap,
                # The patch itself — rendered inline on the HUD callouts.
                "path": command.path,
                "diff": command.diff,
                "change_summary": command.change_summary,
            },
        )
        # A card can never read "blocked" AND "opened" at once. An earlier refusal
        # (throttled, or a guardrail that has since been relaxed — e.g. the old
        # low-confidence gate that became the [UNVERIFIED] label) leaves a
        # ``draft_pr_blocked`` stamp the HUD keeps showing; the success that
        # supersedes it clears it here, in the same locked write, so the operator
        # is never told a PR was refused while looking at the PR.
        meta.pop("draft_pr_blocked", None)

        # Same growable provenance shape the detector/triage pipeline appends to.
        provenance = meta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        unverified = command.verification == "unverified"
        provenance["events"].append(
            {
                "actor": f"agent:{command.acting_agent} via user:{command.performed_by}",
                "action": (
                    f"opened draft PR {command.pr_url} (UNVERIFIED — review carefully)"
                    if unverified
                    else f"opened draft PR {command.pr_url}"
                ),
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
            comment = (
                f"🔧 Draft PR opened for this finding: {command.pr_url} "
                f"(branch `{command.branch}`, repo `{command.pr_repo}`)."
            )
            if unverified:
                comment += (
                    "\n\n⚠️ This PR is labeled UNVERIFIED — the fix could not be grounded "
                    f"against the finding's evidence ({command.verification_gap or 'no named anchor'}). "
                    "Review it carefully before merging."
                )
            TaskComment.objects.create(task=task, author=author, comment=comment)

        return RecordFindingDraftPrResult(recorded=True)

    def mark_draft_pr_rejected(self, *, command: MarkDraftPrRejectedCommand) -> MarkDraftPrRejectedResult:
        """Stamp an existing ``draft_pr`` record as closed-without-merge.

        Lifecycle only — the identity facts and the patch stay verbatim, so the
        rejected attempt remains inspectable. The provenance event is what makes
        the rejection visible on the board: "the operator closed this without
        merging" is a real outcome of an AI action and belongs in the trail.
        """
        from infrastructure.persistence.project.models import Task

        task = Task.objects.filter(id=command.task_id, workspace_id=command.workspace_id).first()
        if task is None:
            return MarkDraftPrRejectedResult(marked=False, reason="task_not_found")

        meta = task.metadata or {}
        record = get_draft_pr(meta)
        if not record.get("url"):
            return MarkDraftPrRejectedResult(marked=False, reason="no_draft_pr_record")
        if record.get("merged"):
            # A merged PR is never "rejected" — the reconciler owns that outcome.
            return MarkDraftPrRejectedResult(marked=False, reason="already_merged")
        if str(record.get("pr_state") or "").lower() == "closed":
            return MarkDraftPrRejectedResult(marked=False, reason="already_rejected")

        rejected_at = datetime.now(UTC).isoformat()
        patched = dict(record)
        patched["pr_state"] = command.pr_state or "closed"
        patched["merged"] = False
        patched["rejected_at"] = rejected_at
        set_draft_pr(meta, patched)

        provenance = meta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        provenance["events"].append(
            {
                "actor": "system:autosec",
                "action": (
                    f"draft PR {record.get('url')} was closed without merging ({command.reason}) — "
                    "the finding stays open and is eligible for a fresh fix attempt"
                ),
                "at": rejected_at,
            }
        )
        meta["provenance"] = provenance
        task.metadata = meta
        task.save(update_fields=["metadata", "updated_at"])
        return MarkDraftPrRejectedResult(marked=True, reason="rejected")

    def attach_draft_pr_patch(self, *, command: AttachDraftPrPatchCommand) -> AttachDraftPrPatchResult:
        """Fill the patch into an existing ``draft_pr`` record (legacy repair path).

        Deliberately narrow: it only ever ADDS ``path`` / ``diff`` /
        ``change_summary`` (plus the PR's lifecycle state) to a record the open
        step already wrote. The identity facts (``url``, ``repo``, ``branch``,
        ``opened_by``, ``opened_at``, ``verification``) are re-written verbatim
        from what is already stored, so a backfill can never rewrite history or
        upgrade a finding's confidence label. No card comment is added — the PR
        was announced when it was opened; this only completes its record.
        """
        from infrastructure.persistence.project.models import Task

        if not (command.diff or "").strip():
            # Never store an empty/fabricated patch — an unreadable PR stays honest.
            return AttachDraftPrPatchResult(attached=False, reason="empty_diff")

        task = Task.objects.filter(id=command.task_id, workspace_id=command.workspace_id).first()
        if task is None:
            return AttachDraftPrPatchResult(attached=False, reason="task_not_found")

        meta = task.metadata or {}
        record = get_draft_pr(meta)
        if not record.get("url"):
            return AttachDraftPrPatchResult(attached=False, reason="no_draft_pr_record")
        if str(record.get("diff") or "").strip():
            # Idempotent: a record that already renders inline is left alone.
            return AttachDraftPrPatchResult(attached=False, reason="already_has_diff")

        attached_at = datetime.now(UTC).isoformat()
        patched = dict(record)
        patched["path"] = command.path
        # Bounded through the ONE contract helper, so a backfilled diff is clamped
        # exactly like one the open step computes.
        patched["diff"] = bound_diff(command.diff)
        patched["change_summary"] = command.change_summary
        if command.pr_state:
            patched["pr_state"] = command.pr_state
            patched["merged"] = bool(command.merged)
        set_draft_pr(meta, patched)

        provenance = meta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        provenance["events"].append(
            {
                "actor": "system:autosec",
                "action": (
                    f"attached the draft PR's patch to this record ({command.reason}) — "
                    f"`{command.path}` now reviewable inline"
                ),
                "at": attached_at,
            }
        )
        meta["provenance"] = provenance
        task.metadata = meta
        task.save(update_fields=["metadata", "updated_at"])
        return AttachDraftPrPatchResult(attached=True, reason="attached")
