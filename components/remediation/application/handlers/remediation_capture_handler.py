"""The trigger that fires the entry-gate when a fix is confirmed applied+resolved.

This is the P3 seam between "a fix landed" and "record it in the corpus". It is a
thin facade over the gated use case: it builds the command and calls
``RemediationService.record``, which independently re-verifies all three
conditions and either admits the entry or refuses (writing nothing). The trigger
does NOT decide admissibility — it only *offers* a candidate; the gate decides.

Why a facade and not an event subscriber (yet) — the honest P4 gap
------------------------------------------------------------------
The architecturally ideal trigger is the moment the third condition becomes true:
a ``FindingResolved`` shared-kernel event AND the finding's task carrying an
applied ``draft_pr`` AND a sign-off-approved record. But today:

- ``FindingResolved`` is a *contract-only* event — nothing emits it yet, and it
  carries ``finding_id``/``fingerprint``, not the board task id the gate keys on.
- **PR merge-detection does not exist** — no PR webhook, no PR-state poll;
  ``metadata.payload.draft_pr`` is written once at open-time and never updated. So
  "applied (merged)" cannot be observed automatically.
- The board triage status never transitions past ``"triaged"`` to ``"resolved"``.

Wiring the gate to those non-firing signals would be a *dead* trigger dressed up
as automation — the shortcut this codebase forbids. Instead the P3 trigger is an
explicit confirmation entry point (called by the operator/agent flow that
confirms a fix was merged and its finding closed). When P4 lands the missing
plumbing — a ``VcsPort.get_pull_request`` / GitHub merge webhook that stamps
``draft_pr.merged`` + a finding-resolved transition that emits ``FindingResolved``
— this same facade becomes the body of that event handler unchanged: only its
*caller* moves from "operator confirmation" to "event subscriber". The gate
itself is already correct and complete.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.remediation.application.commands.record_remediation_entry_command import (
    RecordRemediationEntryCommand,
)
from components.remediation.application.providers.remediation_provider import (
    build_remediation_service,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.domain.errors import EntryGateNotSatisfiedError

logger = logging.getLogger(__name__)


def capture_remediation_if_gated(
    *,
    workspace_id: UUID,
    finding_task_id: str,
    sign_off_artifact_type: str,
    sign_off_artifact_id: str,
    applied_pr_url: str,
    code: str,
    language: str = "",
    title: str = "",
    summary: str = "",
    tags: tuple[str, ...] = (),
    pr_applied: bool = False,
    service=None,
) -> RemediationEntry | None:
    """Offer a candidate fix to the entry-gate.

    Returns the admitted :class:`RemediationEntry` when the gate's three
    conditions all hold, or ``None`` when the gate refuses (the refusal is logged;
    no entry is written). ``service`` is injectable for tests.

    ``pr_applied`` defaults to ``False`` (fail-closed): the "a human confirms this
    merged" flag must be affirmatively set by the caller — a forgotten kwarg must
    never admit an entry. It is still cross-checked against the finding's real
    opened draft-PR URL in the gate, so this is defense-in-depth, not the only
    guard.
    """
    service = service or build_remediation_service()
    command = RecordRemediationEntryCommand(
        workspace_id=workspace_id,
        finding_task_id=finding_task_id,
        sign_off_artifact_type=sign_off_artifact_type,
        sign_off_artifact_id=sign_off_artifact_id,
        pr_applied=pr_applied,
        applied_pr_url=applied_pr_url,
        code=code,
        language=language,
        title=title,
        summary=summary,
        tags=tuple(tags),
    )
    try:
        entry = service.record(command)
    except EntryGateNotSatisfiedError as exc:
        logger.info(
            "remediation_capture_skipped workspace_id=%s finding_task_id=%s unmet=%s",
            workspace_id,
            finding_task_id,
            ",".join(exc.unmet),
        )
        return None

    # The gate ADMITTED the entry (D1) — now make it retrievable (P4). Embedding is
    # the slow part (an LLM/embeddings call), so it is dispatched to Celery AFTER the
    # entry's transaction commits, passing only the ids (never the object). Idempotent
    # by entry id, so a retry or a re-capture re-embeds in place. A dispatch hiccup
    # must never fail the capture — the entry is already safely admitted — so this is
    # loss-tolerant (logged, not raised). This is the sanctioned application-handler
    # role: trigger a side effect after a use case completes.
    _dispatch_embed(entry)
    return entry


def dispatch_embed(entry_id, workspace_id) -> None:
    """Enqueue an entry's (re-)embed after commit — loss-tolerant (P4/P5).

    Reused for both the newly-admitted entry (capture) and a prior whose score
    changed (outcome propagation, P5) — a score change re-embeds so retrieval ranks
    on the new rating. The Celery task module is imported lazily inside the body so
    this application module carries no eager infrastructure/celery import, and the
    dispatch is deferred to ``on_commit`` so the worker never races the writer's
    transaction. Idempotent by entry id; any dispatch failure is logged, never
    raised — embedding is an enhancement, not a gate.
    """
    try:
        from components.remediation.infrastructure.tasks.embed_remediation_entry_tasks import (
            embed_remediation_entry,
        )
        from components.shared_kernel.application.transactional import on_commit

        eid = str(entry_id)
        wsid = str(workspace_id)
        on_commit(lambda: embed_remediation_entry.apply_async(kwargs={"entry_id": eid, "workspace_id": wsid}))
    except Exception:
        logger.exception(
            "remediation_embed_dispatch_failed entry_id=%s workspace_id=%s",
            entry_id,
            workspace_id,
        )


def _dispatch_embed(entry: RemediationEntry) -> None:
    dispatch_embed(entry.id, entry.workspace_id)
