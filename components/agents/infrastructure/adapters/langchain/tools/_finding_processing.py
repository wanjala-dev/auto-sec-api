"""Shared finding-processing core for board-acting specialists.

Both the triage agent (proposes a fix for an error finding) and the optimization
agent (proposes a tuning recommendation for a pattern finding) do the SAME
board choreography: fetch the pending card, run an advisor for a grounded
suggestion, then — under a row lock, re-checking status so overlapping cycles
can't double-act — comment the suggestion, move the card to the acting column,
stamp the handled status, and append a provenance event recording which agent
acted and when.

That choreography lives here ONCE. A specialist supplies only what differs: the
advisor call, the comment text, and which payload fields the suggestion fills.
Copy-pasting the concurrency guard per agent is exactly the kind of duplication
that rots — solve it once.
"""

from __future__ import annotations

import json
import logging

from django.db.models import Q
from django.utils import timezone

from components.shared_kernel.domain.patch_attestation import is_graded
from components.shared_kernel.domain.triage import SOURCE_CODE_SECURITY

logger = logging.getLogger(__name__)

#: The canonical lane a specialist-handled card moves to (ADR 0030 D2): a
#: specialist acting = "In Progress" on the finding's OWN board — the AI state
#: (triaged / optimizing / fix-ready / needs-human) is the
#: ``metadata.triage`` chip, never a bespoke lane. ONE constant shared by the
#: triage / optimization / code-security tools so the acting lane cannot
#: fork per specialist again (dry-reuse.md).
ACTING_COLUMN_TITLE = "In Progress"


def _stamp_patch_attestation(payload: dict, *, acting_agent: str, graded: bool) -> None:
    """Record — or explicitly clear — the proof that this patch was graded.

    Clearing matters as much as stamping. A card re-triaged to a NEW snippet must
    not keep the previous snippet's attestation: the digest binding would catch
    the mismatch, but leaving a stale stamp behind invites reasoning about a claim
    that no longer applies. One pass, one verdict, or none.
    """
    from components.shared_kernel.domain.patch_attestation import (
        PATCH_ATTESTATION_KEY,
        RESULT_PASSED,
        build_attestation,
    )

    before = str(payload.get("fix_before") or "")
    after = str(payload.get("fix_after") or "")
    if not graded or not before.strip() or not after.strip():
        payload.pop(PATCH_ATTESTATION_KEY, None)
        return
    payload[PATCH_ATTESTATION_KEY] = build_attestation(
        verifier=acting_agent,
        fix_before=before,
        fix_after=after,
        result=RESULT_PASSED,
        verified_at=timezone.now().isoformat(),
    )


def not_triaged_filter() -> Q:
    """A NULL-safe "finding not yet handled" filter.

    ``.exclude(metadata__triage__status="triaged")`` looks correct but silently
    drops rows where ``metadata.triage`` is ABSENT — Postgres evaluates
    ``NOT (NULL = 'triaged')`` as NULL, which the WHERE clause treats as false,
    so genuinely-fresh findings (no triage key yet) vanish from the query. That
    bug hid every un-stamped finding from the router. This keeps a row when the
    status is missing OR anything other than ``triaged``.
    """
    return Q(metadata__triage__status__isnull=True) | ~Q(metadata__triage__status="triaged")


def _resolve_user(agent):
    from infrastructure.persistence.users.models import CustomUser

    try:
        return CustomUser.objects.get(id=agent.user_id)
    except (CustomUser.DoesNotExist, ValueError, TypeError):
        from infrastructure.persistence.workspaces.models import Workspace

        ws = Workspace.objects.all_objects().filter(id=agent.workspace_id).first()
        return ws.workspace_owner if ws else None


def ensure_board_column(team, workspace, creator, title, *, project_id=None):
    """Return the board's column with ``title``, creating it once.

    ``project_id=None`` addresses the team board (project-less columns);
    a project id addresses that project's board — ADR 0030 P3 moved the
    specialist move onto the finding's OWN project board (the AI Findings
    canonical lanes), so the destination column shares the task's
    team + project by construction.

    A NEW column lands AFTER every existing lane: ``max(order) + 1`` over the
    board's sibling columns. (The previous ``first().order + 1`` took the
    MINIMUM, so any auto-created column collided with an existing lane's order
    — Triage landing on Todo's slot on a default board; QA report 2026-08-16,
    F8.) The max is computed under ``select_for_update`` on the sibling rows,
    in the same transaction as the create, so two concurrent creates of
    DIFFERENT titles can't mint the same slot. For the SAME title,
    ``get_or_create`` (plus, on team boards, the DB partial-unique constraint
    on ``(team, workspace, title) where project is null``) stays the guard —
    the loser hits the constraint and re-reads. Soft-deleted columns are
    never adopted (``is_deleted=False`` in the lookup) — a lane the P3
    migration retired stays retired.
    """
    from django.db import transaction
    from django.db.models import Max

    from infrastructure.persistence.project.models import Column

    team_id = getattr(team, "id", team)  # accepts an instance or a pk
    with transaction.atomic():
        siblings = Column.objects.select_for_update().filter(
            team_id=team_id, workspace=workspace, project_id=project_id
        )
        max_order = siblings.aggregate(max_order=Max("order"))["max_order"]
        column, _ = Column.objects.get_or_create(
            team_id=team_id,
            workspace=workspace,
            project_id=project_id,
            title=title,
            is_deleted=False,
            defaults={"order": (max_order or 0) + 1, "created_by": creator},
        )
    return column


def pending_findings_qs(workspace_id, source_type, limit=50):
    """Un-handled findings of a source_type, newest first, capped.

    The handled-exclusion is pushed into the query (Postgres JSON path) so the
    scan stays bounded as finding history grows.
    """
    from infrastructure.persistence.project.models import Task

    return list(
        Task.objects.filter(workspace_id=workspace_id, source_type=source_type)
        .filter(not_triaged_filter())
        .select_related("column", "team")
        .order_by("-created_at")[:limit]
    )


def _handled_with_suggestion(metadata: dict, *, source_type: str = "") -> bool:
    """True when this finding was already triaged AND carries what its source needs.

    The idempotency guard for ``process_pending_finding``. A triaged card whose
    outcome was NO FIX (``suggested`` falsy and nothing in ``payload.suggested_fix``)
    deliberately does NOT count as handled: the no-fix state is re-attemptable —
    the operator's retry re-runs the advisor with fresh context instead of
    bouncing off "already handled".

    For SAST, "what its source needs" is a GRADED patch, not prose — the same
    question ``draft_fix_for_finding``'s re-run gate asks, deliberately answered by
    the same predicate (ADR 0025 P2c). Two definitions of "handled" is what broke:
    the gate decided a card needed re-grading, dispatched a real deep run, and this
    guard then returned "already handled" because month-old advice text was
    present. The run burned tokens, changed nothing, and the engine fell through to
    the ungraded advisor anyway — the gate was inert for exactly the cards it
    existed for. Measured live on card 9975, which came back byte-identical.
    """
    meta = metadata or {}
    triage = meta.get("triage") or {}
    if triage.get("status") != "triaged":
        return False
    payload = meta.get("payload") or {}
    if (source_type or "") == SOURCE_CODE_SECURITY:
        return is_graded(payload)
    return bool(triage.get("suggested")) or bool(str(payload.get("suggested_fix") or "").strip())


def _parse_task_id(input_str):
    raw = (input_str or "").strip()
    try:
        data = json.loads(raw) if raw.startswith("{") else {"task_id": raw}
    except (ValueError, TypeError):
        data = {"task_id": raw}
    return (data.get("task_id") or "").strip()


def process_pending_finding(
    agent,
    input_str,
    *,
    source_type,
    column_title,
    acting_agent,
    advise,
    build_comment,
    apply_payload,
    describe_action,
    suggestion_text=None,
    patch_text=None,
):
    """Handle one pending finding end-to-end (advise → verify → comment → move → stamp).

    Args:
        source_type: the finding's ``Task.source_type`` (e.g. ``ai.log_watch``).
        column_title: board column the handled card moves to.
        acting_agent: attribution string (e.g. ``triage_agent``).
        advise(payload, feedback="") -> suggestion|None: the (slow) LLM step, run
            OUTSIDE the row lock. ``feedback`` is passed on a grounded re-advise.
        build_comment(suggestion|None) -> str: the card comment body.
        apply_payload(payload, suggestion) -> None: mutate the finding payload
            in place with the suggestion's fields (only when suggestion truthy).
        describe_action(suggestion|None) -> str: short verb phrase for the
            actions list + the provenance event.
        suggestion_text(suggestion) -> str: extract the gradeable text from the
            suggestion. When provided, enables the GROUNDED verifier — the
            suggestion is checked against the finding's evidence (deterministic,
            no LLM); an ungrounded suggestion triggers ONE grounded re-advise,
            and if still ungrounded the card is committed with the verification
            LABEL downgraded to ``unverified`` + the named evidence gap. The
            verifier is a labeler, not a gate: the fix still flows to a draft PR
            (loudly marked UNVERIFIED) because a draft PR cannot merge itself —
            the PR is the human review surface. A confident-but-ungrounded fix
            is never presented as verified. See finding_verifier.py + the
            ICLR-2024 rationale.
        patch_text(suggestion) -> str: extract the PROPOSED replacement code (a
            SAST suggestion's ``fix_after``). Optional, and deliberately separate
            from ``suggestion_text``: the grounding text includes the OFFENDING
            line so a fix that quotes it counts as anchored, which means running
            the remediation anti-patterns over it would match the vulnerability
            every time and reject every fix. Supplying this enables the
            fix-SHAPE check (ADR 0019 D5) — a patch that reproduces a known-wrong
            shape for its rule class is sent back through the SAME single
            re-advise below, carrying the reason, and if it survives it ships
            labeled unverified rather than silently wrong. Omit it and behaviour
            is exactly as before.
    """
    from django.db import transaction

    from infrastructure.persistence.project.models import Task, TaskComment
    from infrastructure.persistence.workspaces.models import Workspace

    task_id = _parse_task_id(input_str)
    if not task_id:
        return "task_id is required to process a finding."

    task = (
        Task.objects.filter(id=task_id, workspace_id=agent.workspace_id, source_type=source_type)
        .select_related("team", "column", "project")
        .first()
    )
    if task is None:
        return f"No {source_type} finding {task_id} on this workspace's board."

    meta = task.metadata or {}
    # Fast path — already handled WITH a suggestion (avoids a wasted LLM call when
    # a prior run, or an overlapping cycle, already processed this finding). A
    # triaged card that ended in NO FIX stays re-attemptable: the operator's
    # retry (the on-demand draft-fix action) must be able to re-run the advisor
    # rather than dead-ending on "already handled".
    if _handled_with_suggestion(meta, source_type=source_type):
        return f"Finding {task_id} was already handled."

    payload = meta.get("payload") or {}
    # Advisor runs OUTSIDE the row lock (it's the slow part) — the board mutation
    # below re-locks and re-checks so we never double-comment.
    suggestion = advise(payload)

    # Grounded verification (L2 core) — check the suggestion against the finding's
    # EVIDENCE, not the model's own belief. An ungrounded suggestion gets ONE
    # grounded re-advise; if still ungrounded the suggestion is LABELED
    # ``unverified`` with the named evidence gap — never presented as verified,
    # and never withheld (the label, not a missing artifact, is the honest
    # signal). Deterministic; only runs when a text extractor is supplied. See
    # finding_verifier.py (Huang et al., ICLR 2024).
    verification = ""
    verify_reason = ""
    if suggestion is not None and suggestion_text is not None:
        from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import verify_suggestion

        vr = verify_suggestion(
            source_type=source_type,
            payload=payload,
            suggestion_text=suggestion_text(suggestion) or "",
            patch_code=(patch_text(suggestion) or "") if patch_text is not None else None,
        )
        if not vr.grounded:
            retry = advise(payload, feedback=vr.reason)
            if retry is not None:
                suggestion = retry
                vr = verify_suggestion(
                    source_type=source_type,
                    payload=payload,
                    suggestion_text=suggestion_text(retry) or "",
                    patch_code=(patch_text(retry) or "") if patch_text is not None else None,
                )
        verification = "verified" if vr.grounded else "unverified"
        if not vr.grounded:
            verify_reason = vr.reason
            logger.info(
                "process_finding ungrounded task_id=%s agent=%s reason=%s",
                task_id,
                acting_agent,
                vr.reason,
            )
    unverified = verification == "unverified"

    creator = _resolve_user(agent)
    workspace = Workspace.objects.all_objects().filter(id=agent.workspace_id).first()

    comment_body = build_comment(suggestion)
    action_phrase = describe_action(suggestion)
    if unverified:
        comment_body += (
            "\n\n⚠️ This suggestion could not be grounded in the finding's evidence "
            f"({verify_reason}). It still flows to a draft PR — clearly labeled "
            "UNVERIFIED — because the draft PR is the human review surface; review "
            "it carefully before merging."
        )
        action_phrase = f"{action_phrase} (unverified — could not be grounded)"
    actions = [action_phrase]

    # Serialize the board mutation on the finding row: two overlapping cycles
    # both hold suggestions, but only the first through the lock acts — the
    # second sees ``triaged`` and no-ops (no duplicate comment / move).
    with transaction.atomic():
        # Lock ONLY the task row (``of=("self",)``) — locking a nullable FK's
        # outer join (``column``) is rejected by Postgres, and we only need to
        # serialize writes to the finding itself. ``task`` (fetched above with
        # team/column) supplies the team for the column resolve.
        locked = (
            Task.objects.select_for_update(of=("self",))
            .filter(id=task_id, workspace_id=agent.workspace_id, source_type=source_type)
            .first()
        )
        if locked is None:
            return f"No {source_type} finding {task_id} on this workspace's board."
        lmeta = locked.metadata or {}
        if _handled_with_suggestion(lmeta, source_type=source_type):
            return f"Finding {task_id} was already handled (concurrent run)."

        lpayload = lmeta.get("payload") or {}
        if suggestion is not None:
            apply_payload(lpayload, suggestion)
        # The verifier's verdict is a LABEL on the suggestion, not a gate in
        # front of the artifact: ``unverified`` + the named gap ride the payload
        # so the draft-PR engine can mark the PR (title/body) and the HUD can say
        # "review carefully" — the fix itself still ships. ``apply_payload`` may
        # have already downgraded (e.g. untrusted source content); a downgrade
        # always wins over the verifier's pass.
        if verification and lpayload.get("verification") != "unverified":
            lpayload["verification"] = verification
            lpayload["verification_gap"] = verify_reason
        final_verification = str(lpayload.get("verification") or verification)
        final_gap = str(lpayload.get("verification_gap") or verify_reason)
        unverified = final_verification == "unverified"
        # Attest to the patch we just graded, bound to its content (ADR 0025 P2c).
        # This is the ONLY place a passing attestation is minted, and it is minted
        # here because this is where the oracles actually ran. Downstream, the
        # draft-PR engine replays a snippet only against a matching attestation —
        # so a snippet that never faced the grader (every card triaged before it
        # existed) can no longer inherit a "verified" label from the mere fact
        # that a snippet is present.
        if patch_text is not None:
            _stamp_patch_attestation(
                lpayload,
                acting_agent=acting_agent,
                graded=bool(verification) and not unverified,
            )
        if unverified:
            # Kept for the posture/run-quality consumers that count the
            # "needs a careful human" backlog — same fact, richer label above.
            lpayload["needs_human"] = True

        if creator is not None:
            TaskComment.objects.create(task=locked, author=creator, comment=comment_body)
            actions.append("posted comment")

        moved = False
        if task.team is not None and workspace is not None:
            # The destination lane lives on the finding's OWN board — its
            # project's board when it has one (the AI Findings canonical
            # lanes), the team board otherwise. When the task carries a
            # project, the project's team wins over a (possibly stale)
            # ``task.team`` so the resolved column is internally consistent.
            dest_team_id = task.project.team_id if task.project is not None else task.team_id
            col = ensure_board_column(
                dest_team_id,
                workspace,
                creator,
                column_title,
                project_id=task.project_id,
            )
            if col and locked.column_id != col.id:
                # MoveTaskToBoardView semantics (QA F1): the destination board
                # is the COLUMN's own team + project — deriving all three FKs
                # from the destination column makes the stale-project
                # inconsistency impossible by construction, not by discipline.
                locked.column = col
                locked.team_id = col.team_id
                locked.project_id = col.project_id
                moved = True
                actions.append(f"moved to {column_title} column")

        handled_at = timezone.now().isoformat()
        lmeta["payload"] = lpayload
        lmeta["triage"] = {
            "status": "triaged",
            "agent": acting_agent,
            "triaged_at": handled_at,
            "actions": actions,
            "suggested": suggestion is not None,
            # ``verification``/``verification_gap`` are the honest labels; the
            # boolean stays for the posture/run-quality backlog consumers.
            "verification": final_verification,
            "verification_gap": final_gap,
            "needs_human": unverified,
            # NO-FIX outcomes carry WHY (the specialist's own phrase) so the
            # state the HUD derives is informative, never a dead-end blank.
            "no_fix_reason": action_phrase if suggestion is None else "",
        }
        # Append to the growable provenance audit trail (created by the detector
        # at file time) — records that THIS agent acted, and when.
        provenance = lmeta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        provenance["events"].append(
            {
                "actor": f"agent:{acting_agent}",
                "action": action_phrase,
                "at": handled_at,
                "moved": moved,
            }
        )
        provenance["last_handled_by"] = acting_agent
        provenance["last_handled_at"] = handled_at
        lmeta["provenance"] = provenance
        locked.metadata = lmeta
        update_fields = ["metadata", "updated_at"]
        if moved:
            # team/project ride along with column (MoveTaskToBoardView
            # semantics). The workflow_status mirror is handled by the P1
            # sync bridge: its pre_save resolves the mirror because "column"
            # is in update_fields, and its post_save persists the mirror this
            # partial save would otherwise drop.
            update_fields.extend(["column", "team", "project"])
        locked.save(update_fields=update_fields)

        # THE HAND-OFF. A suggested fix is not an artifact — the artifact is the
        # draft PR. Before this, triage stopped at "suggested a code fix" and the
        # PR only ever opened when an operator asked for one, so a finding in a
        # connected repo sat on the board reading FIX READY with nothing behind
        # it (13 of 15 repo findings in the demo workspace). Henry's standing
        # rule: a finding in a connected repository ALWAYS carries its draft PR;
        # a grounding failure downgrades the LABEL, never withholds the artifact.
        #
        # Dispatched AFTER COMMIT (celery invariant): the worker re-reads this
        # card, so enqueuing inside the transaction races its own write. IDs
        # only, never objects. Every guardrail still lives in the ONE PR engine
        # (patch scope, validate_patch, the per-repo throttle, the connection +
        # repo allowlist, the agent capability) and each refusal is still
        # recorded on the card — this only removes the missing trigger, it does
        # not weaken a single check.
        if suggestion is not None:
            _dispatch_draft_pr_after_commit(
                transaction,
                workspace_id=str(agent.workspace_id),
                task_id=str(task_id),
                source_type=source_type,
                metadata=lmeta,
                acting_agent=acting_agent,
                performed_by=str(getattr(creator, "id", "") or ""),
            )

    logger.info(
        "process_finding source_type=%s task_id=%s agent=%s advised=%s moved=%s",
        source_type,
        task_id,
        acting_agent,
        suggestion is not None,
        moved,
    )
    return f"Handled {task.title[:70]}: {', '.join(actions)}."


def _dispatch_draft_pr_after_commit(
    transaction,
    *,
    workspace_id: str,
    task_id: str,
    source_type: str,
    metadata: dict,
    acting_agent: str,
    performed_by: str,
) -> None:
    """Queue the finding's draft PR once the triage write is durable.

    Skips (silently, by design) when the finding has no repository to open a PR
    against — an image/cloud/service finding's artifact is its fix snippet or
    guidance, and stamping "PR blocked" on a finding that never had a PR path is
    the misleading noise the target distinction exists to remove. Also skips a
    finding that already carries a draft PR, so a re-triage never opens a second.

    Never raises: a dispatch failure must not roll back or fail the triage that
    already succeeded — the fix is on the card either way, and the cadence /
    on-demand triggers remain as the retry path.
    """
    from components.shared_kernel.domain.triage import TARGET_REPO, remediation_target

    payload = (metadata or {}).get("payload") or {}
    if remediation_target(source_type, payload) != TARGET_REPO:
        return
    if (payload.get("draft_pr") or {}).get("url"):
        return
    if not performed_by:
        # The open step needs an acting identity for commit attribution + audit.
        # Without one we would open a PR nobody can be held to — refuse loudly in
        # the log rather than attribute it to no one.
        logger.warning(
            "auto draft-PR skipped (no acting user) workspace_id=%s task_id=%s agent=%s",
            workspace_id,
            task_id,
            acting_agent,
        )
        return

    def _enqueue():
        from components.agents.infrastructure.tasks.agent_tasks import auto_draft_pr_for_finding

        auto_draft_pr_for_finding.delay(
            workspace_id=workspace_id, task_id=task_id, performed_by=performed_by, acting_agent=acting_agent
        )
        logger.info("auto draft-PR dispatched workspace_id=%s task_id=%s agent=%s", workspace_id, task_id, acting_agent)

    transaction.on_commit(_enqueue)


def _telemetry_entry_for(per_task_map, finding_id: str):
    """Resolve a finding's entry from a run's per-task telemetry map.

    ``rubric_verdicts`` / ``critic_scores`` are keyed by the PLAN task id the
    deep runner dispatched — which is normally NOT the finding row's id (the
    specialist processes findings through its tools, one plan task can cover a
    whole batch). Resolution order:

    1. exact key match (a plan task that IS the finding — future-proofing);
    2. a single-entry map → that entry graded the whole batch, so it applies
       to every finding the batch handled (marked ``scope: "run"``);
    3. otherwise ``None`` — ambiguous attribution is not fabricated.
    """
    if not isinstance(per_task_map, dict) or not per_task_map:
        return None
    entry = per_task_map.get(finding_id)
    if isinstance(entry, dict):
        return {**entry, "scope": "task"}
    if len(per_task_map) == 1:
        only = next(iter(per_task_map.values()))
        if isinstance(only, dict):
            return {**only, "scope": "run"}
    return None


def stamp_run_telemetry_on_findings(*, workspace_id, specialist, since, run_result) -> int:
    """Persist a specialist run's telemetry onto the finding rows it handled.

    The async dispatch path (``dispatch_finding_specialist`` →
    ``execute_agent`` → ``execute_plan_once``) produces a final state whose
    ``run_metadata`` carries the run's A/B telemetry — rubric verdicts, critic
    scores, worker retries, budget exhaustion — and then DROPPED it (no
    DeepRun consumer reads it on this path). This stamps the relevant slice
    onto ``Task.metadata["run_telemetry"]`` of each finding the specialist
    triaged during the run, next to the existing triage/provenance stamps —
    so the quality data lives where the operator sees the finding, and the
    ``AgentRunQualityDetector`` can aggregate it.

    Handled findings are matched deterministically: rows this specialist
    stamped ``metadata.triage.agent == specialist`` on, updated after the
    dispatch started. Runs AFTER the deep run completes, and re-locks each row
    (same ``select_for_update(of=("self",))`` discipline as the triage write)
    so it never races an overlapping cycle's row-locked triage mutation.

    Fail-safe end to end: any error degrades to a log line — telemetry must
    never fail (or retry) the dispatch. Returns the number of rows stamped.
    """
    from django.db import transaction
    from django.utils import timezone

    from infrastructure.persistence.project.models import Task

    try:
        final = run_result.get("final_output") if isinstance(run_result, dict) else None
        run_metadata = final.get("run_metadata") if isinstance(final, dict) else None
        if not isinstance(run_metadata, dict) or not run_metadata:
            return 0
        thread_id = str(run_result.get("thread_id") or "") or None
        rubric_map = run_metadata.get("rubric_verdicts") or {}
        critic_map = run_metadata.get("critic_scores") or {}
        retries_map = run_metadata.get("worker_retries") or {}
        try:
            total_retries = sum(int(v) for v in retries_map.values() if v is not None)
        except (TypeError, ValueError):
            total_retries = 0
        budget_exceeded = run_metadata.get("budget_exceeded_reason") or (
            final.get("budget_exceeded") if isinstance(final, dict) else None
        )

        handled_ids = list(
            Task.objects.filter(
                workspace_id=workspace_id,
                source_type__startswith="ai.",
                metadata__triage__agent=specialist,
                updated_at__gte=since,
            ).values_list("id", flat=True)
        )
        if not handled_ids:
            return 0

        stamped = 0
        stamped_at = timezone.now().isoformat()
        for finding_id in handled_ids:
            try:
                with transaction.atomic():
                    locked = Task.objects.select_for_update(of=("self",)).filter(id=finding_id).first()
                    if locked is None:
                        continue
                    meta = locked.metadata or {}
                    if (meta.get("triage") or {}).get("agent") != specialist:
                        continue  # re-check under the lock — an overlapping run may have re-stamped
                    meta["run_telemetry"] = {
                        "rubric_verdicts": _telemetry_entry_for(rubric_map, str(finding_id)),
                        "critic_scores": _telemetry_entry_for(critic_map, str(finding_id)),
                        "worker_retries": total_retries,
                        "budget_exceeded": budget_exceeded or None,
                        "source_thread_id": thread_id,
                        "specialist": specialist,
                        "stamped_at": stamped_at,
                    }
                    locked.metadata = meta
                    locked.save(update_fields=["metadata", "updated_at"])
                    stamped += 1
            except Exception:
                logger.exception(
                    "run_telemetry stamp failed finding_id=%s specialist=%s",
                    finding_id,
                    specialist,
                )
        logger.info(
            "run_telemetry stamped workspace_id=%s specialist=%s thread_id=%s findings=%d",
            workspace_id,
            specialist,
            thread_id,
            stamped,
        )
        return stamped
    except Exception:
        logger.exception(
            "run_telemetry stamp aborted workspace_id=%s specialist=%s",
            workspace_id,
            specialist,
        )
        return 0
