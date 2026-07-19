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

logger = logging.getLogger(__name__)


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


def ensure_board_column(team, workspace, creator, title):
    """Return the board's column with ``title``, creating it once.

    ``get_or_create`` + the DB partial-unique constraint on
    ``(team, workspace, title) where project is null`` make this safe under
    concurrent runs — the loser hits the constraint and re-reads.
    """
    from infrastructure.persistence.project.models import Column

    intake = Column.objects.filter(team=team, workspace=workspace, project__isnull=True).order_by("order").first()
    order = (intake.order + 1) if intake is not None else 1
    column, _ = Column.objects.get_or_create(
        team=team,
        workspace=workspace,
        project=None,
        title=title,
        defaults={"order": order, "created_by": creator},
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
            and if still ungrounded the card is committed but confidence is
            downgraded and it is flagged ``needs_human`` (never ship a confident
            but ungrounded fix). See finding_verifier.py + the ICLR-2024 rationale.
    """
    from django.db import transaction

    from infrastructure.persistence.project.models import Task, TaskComment
    from infrastructure.persistence.workspaces.models import Workspace

    task_id = _parse_task_id(input_str)
    if not task_id:
        return "task_id is required to process a finding."

    task = (
        Task.objects.filter(id=task_id, workspace_id=agent.workspace_id, source_type=source_type)
        .select_related("team", "column")
        .first()
    )
    if task is None:
        return f"No {source_type} finding {task_id} on this workspace's board."

    meta = task.metadata or {}
    # Fast path — already handled (avoids a wasted LLM call when a prior run, or
    # an overlapping cycle, already processed this finding).
    if (meta.get("triage") or {}).get("status") == "triaged":
        return f"Finding {task_id} was already handled."

    payload = meta.get("payload") or {}
    # Advisor runs OUTSIDE the row lock (it's the slow part) — the board mutation
    # below re-locks and re-checks so we never double-comment.
    suggestion = advise(payload)

    # Grounded verification (L2 core) — check the suggestion against the finding's
    # EVIDENCE, not the model's own belief. An ungrounded suggestion gets ONE
    # grounded re-advise; if still ungrounded we flag needs_human rather than ship
    # a confident-but-baseless fix. Deterministic; only runs when a text extractor
    # is supplied. See finding_verifier.py (Huang et al., ICLR 2024).
    needs_human = False
    verify_reason = ""
    if suggestion is not None and suggestion_text is not None:
        from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import verify_suggestion

        vr = verify_suggestion(
            source_type=source_type, payload=payload, suggestion_text=suggestion_text(suggestion) or ""
        )
        if not vr.grounded:
            retry = advise(payload, feedback=vr.reason)
            if retry is not None:
                suggestion = retry
                vr = verify_suggestion(
                    source_type=source_type, payload=payload, suggestion_text=suggestion_text(retry) or ""
                )
            if not vr.grounded:
                needs_human = True
                verify_reason = vr.reason
                logger.info(
                    "process_finding ungrounded task_id=%s agent=%s reason=%s",
                    task_id,
                    acting_agent,
                    vr.reason,
                )

    creator = _resolve_user(agent)
    workspace = Workspace.objects.all_objects().filter(id=agent.workspace_id).first()

    comment_body = build_comment(suggestion)
    action_phrase = describe_action(suggestion)
    if needs_human:
        comment_body += (
            "\n\n⚠️ This suggestion could not be grounded in the finding's evidence "
            f"({verify_reason}) — flagged for human review."
        )
        action_phrase = f"{action_phrase} (flagged for human review — ungrounded)"
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
        if (lmeta.get("triage") or {}).get("status") == "triaged":
            return f"Finding {task_id} was already handled (concurrent run)."

        lpayload = lmeta.get("payload") or {}
        if suggestion is not None:
            apply_payload(lpayload, suggestion)
        if needs_human:
            # Ungrounded after a re-advise — commit it (so the operator sees the
            # attempt) but downgrade confidence and flag for human review.
            lpayload["needs_human"] = True
            lpayload["confidence"] = "low"

        if creator is not None:
            TaskComment.objects.create(task=locked, author=creator, comment=comment_body)
            actions.append("posted comment")

        moved = False
        if task.team is not None and workspace is not None:
            col = ensure_board_column(task.team, workspace, creator, column_title)
            if col and locked.column_id != col.id:
                locked.column = col
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
            "needs_human": needs_human,
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
            update_fields.append("column")
        locked.save(update_fields=update_fields)

    logger.info(
        "process_finding source_type=%s task_id=%s agent=%s advised=%s moved=%s",
        source_type,
        task_id,
        acting_agent,
        suggestion is not None,
        moved,
    )
    return f"Handled {task.title[:70]}: {', '.join(actions)}."
