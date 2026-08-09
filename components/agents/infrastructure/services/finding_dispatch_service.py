"""The ONE finding→specialist routing engine — shared by the cadence and the
immediate (on-detection / on-demand) paths.

Findings used to sit between "detected" and "fix proposed" for up to a full beat
tick: a scan files cards instantly, but only the 5-minutely
``AiFindingRouterDetector`` grouped the pending cards by their declared
``metadata.agent_type`` and enqueued ``dispatch_finding_specialist``. This module
lifts that grouping / lease / enqueue choreography out of the detector so THREE
triggers drive the SAME engine (dry-reuse: one canonical thing per concern):

1. **On detection** — ``request_specialist_dispatch`` is called from the finding
   board handler the moment a routable card exists.
2. **Cadence** — ``dispatch_pending_findings`` is still what the detector runs
   every tick; it remains the backstop that sweeps anything the immediate path
   missed (a burst that outran the debounce window, a gate that was off, a lost
   task).
3. **On demand** — the operator's per-finding "draft fix" action (see
   ``triage_finding_now`` in ``infrastructure/tasks/agent_tasks.py``) reuses the
   same lease so a click can never double-fire against an in-flight dispatch.

**Why the board handler and not ``ScanCompleted``.** ``ScanCompleted`` reads like
the natural "the scan just finished" hook, but every domain event is delivered as
its own Celery task: a finding travels ``FindingObserved`` → findings SSOT →
``FindingRaised`` → board card, two hops AFTER the ``ScanCompleted`` task is
already queued. A dispatch hung off ``ScanCompleted`` would routinely run against
an empty backlog, burn the lease, and leave the findings waiting for the cadence —
exactly the gap being closed. The board handler fires at the only moment the
precondition actually holds: a routable card EXISTS. It is also source-agnostic —
log-watch findings never come from a scan at all.

**Bounded fan-out.** ``request_specialist_dispatch`` is O(1) per finding (one
cache op, no query) and the existing per-``(workspace, specialist)`` lease is what
collapses a 500-finding scan into ONE dispatch carrying all of them — the
specialist lists its own pending findings when it runs. The immediate enqueue also
carries a short ``countdown`` so a burst coalesces into a single run instead of a
run that sees only the first card.
"""

from __future__ import annotations

import logging

from components.agents.application.ports.finding_dispatch_port import (
    DraftFixRefused,
    FindingDispatchPort,
)
from components.project.application.ports.record_finding_draft_pr_port import get_draft_pr
from components.shared_kernel.domain.triage import (
    DISPATCH_STAMP_TTL_SECONDS,
    NON_SPECIALIST_AGENT_TYPES,
    ROUTABLE_SOURCE_TYPES,
    TARGET_REPO,
    TriageState,
    is_routable_to_specialist,
    remediation_target,
)

logger = logging.getLogger(__name__)

# Re-exported from the shared-kernel triage contract (C1: the routing vocabulary is
# shared by agents/findings/project, so it lives in the kernel, not here). Kept as
# module names so existing callers and tests read them off this service unchanged.
NON_SPECIALIST = NON_SPECIALIST_AGENT_TYPES

# A dispatch to a specialist is leased in the cache for this long so overlapping
# cycles (beat cadence == the run's time limit), an immediate dispatch, and an
# operator click can't fire redundant deep runs for the same specialist. Longer
# than one cycle, shorter than a long backlog stall. Correctness is still
# guaranteed by ``process_pending_finding``'s row lock; the lease only saves
# wasted deep runs + LLM spend.
DISPATCH_LEASE_SECONDS = 240

# Debounce for the immediate path: a scan files its cards one event-task at a
# time, so the first card must NOT start the specialist instantly or the run
# sees a batch of one. Short enough to feel immediate (the HUD shows QUEUED FOR
# TRIAGE meanwhile), long enough for a normal scan's cards to land together.
IMMEDIATE_DEBOUNCE_SECONDS = 20

# The DRAFTING-stamp lifetime is part of the shared triage contract (re-exported
# here so callers of this engine read one name).
_STAMP_TTL = DISPATCH_STAMP_TTL_SECONDS

# Double-click guard for the operator's on-demand button, sized to the task's hard
# time limit so the lease outlives the run it protects.
DRAFT_FIX_LEASE_SECONDS = 600


def build_specialist_goal(count: int | None = None) -> str:
    """The dispatch goal text — ONE builder for every trigger."""
    how_many = f"are {count} pending findings" if count else "are pending findings"
    return (
        f"There {how_many} on the SOC board assigned to you. "
        "Use your tools to list them and process each one (propose a fix, comment it, "
        "and advance the card)."
    )


def build_finding_goal(task_id: str, metadata: dict) -> str:
    """The goal for a SINGLE-finding on-demand run.

    The identifiers are spelled out in the goal, not just the context, because the
    specialist's triage tool is driven by the goal text — a run told only "triage a
    finding" would have to guess which one. Location/rule facts come straight off
    the card so the specialist grounds on the scan's own evidence.
    """
    payload = (metadata or {}).get("payload") or {}
    where = ""
    if payload.get("path"):
        where = f" at {payload.get('path')}:{payload.get('start_line') or '?'}"
        if payload.get("repo"):
            where = f" in {payload['repo']}{where}"
    rule = f" (rule {payload['rule_id']})" if payload.get("rule_id") else ""
    return (
        f"An operator asked you to draft a fix for finding {task_id}{where}{rule}. "
        f'Triage exactly that one finding — call your triage tool with {{"task_id": "{task_id}"}} — '
        "and ground the fix in the real file content at the scanned commit. "
        "Do not triage any other finding in this run."
    )


def build_finding_agent_context(specialist: str, task_id: str, metadata: dict) -> dict:
    """Deep-run context for a single-finding run, carrying the finding's facts.

    The specialist should never have to re-derive (or invent) where the finding is:
    the scan already resolved it. Everything here is board-stored data — no secret,
    and no untrusted code snippet (the snippet stays on the card, read through the
    tool's own sanitized path).
    """
    payload = (metadata or {}).get("payload") or {}
    context = build_agent_context(specialist, source="on_demand.draft_fix")
    context.update(
        {
            "finding_task_id": str(task_id),
            "finding_task_ids": [str(task_id)],
            "finding_id": str(payload.get("finding_id") or ""),
            "repo": str(payload.get("repo") or ""),
            "commit_sha": str(payload.get("commit_sha") or ""),
            "path": str(payload.get("path") or ""),
            "start_line": payload.get("start_line") or 0,
            "end_line": payload.get("end_line") or 0,
            "rule_id": str(payload.get("rule_id") or ""),
            "severity": str(payload.get("severity") or ""),
        }
    )
    return context


def build_agent_context(specialist: str, *, source: str) -> dict:
    """The deep-run context every dispatch carries.

    ``mode`` / ``worker_agent_type`` / ``max_reflections`` are only read by
    ``_execute_deep``; without them the specialist ``Agent`` row's own config picks
    the mode and a row with ``mode=None`` silently drops to the plain executor,
    where those keys are dead and no telemetry exists (§5.13).
    """
    return {
        "mode": "deep",
        "worker_agent_type": specialist,
        "source": source,
        # Verification loop (L2): the specialist self-verifies its finding output
        # and re-runs once on a failing grade.
        "max_reflections": 1,
    }


def is_routable(source_type: str, specialist: str) -> bool:
    """True when a card of *source_type* declaring *specialist* is dispatchable."""
    return is_routable_to_specialist(source_type, specialist)


def ai_dispatch_allowed(workspace_id) -> bool:
    """The shared gate stack for ANY specialist dispatch.

    Deliberately the same gates the cadence already honours, so the immediate path
    can never reach further than the beat could:

    * ``Workspace.ai_teammate_enabled`` — the product toggle the beat fan-out
      (``iter_enabled_seeds``) filters on. The immediate path does not run through
      that fan-out, so it must check the field itself or it would silently ignore a
      workspace that turned AI off.
    * ``feature.ai_kill_switch`` — the operator break-glass. It halts the detector
      cycle today; it must halt this too, or a trip would stop the cadence while
      scans kept firing runs.

    The agent ENTITLEMENT gate lives one layer down in ``dispatch_finding_specialist``
    → ``_delegate_to_agent`` → ``resolve_agent_entitlement``, so it applies to every
    trigger without being restated here.

    Fail-safe: any error → False. The worst case is today's behaviour (the cadence
    picks the findings up), never an unbudgeted fan-out of deep runs.
    """
    from components.agents.application.policies.ai_kill_switch import is_ai_killed
    from infrastructure.persistence.workspaces.models import Workspace

    try:
        enabled = (
            Workspace.objects.all_objects()
            .filter(id=workspace_id)
            .values_list("ai_teammate_enabled", flat=True)
            .first()
        )
        if not enabled:
            return False
        return not is_ai_killed(str(workspace_id))
    except Exception:
        logger.exception("ai_dispatch_gate_check_failed workspace_id=%s", workspace_id)
        return False


def acquire_dispatch_lease(workspace_id, specialist: str) -> bool:
    """Claim the per-``(workspace, specialist)`` dispatch lease. False → in flight."""
    from django.core.cache import cache

    return bool(cache.add(dispatch_lease_key(workspace_id, specialist), "1", DISPATCH_LEASE_SECONDS))


def dispatch_lease_key(workspace_id, specialist: str) -> str:
    """The one lease key format — shared by the cadence, the immediate path, and
    the on-demand action so all three contend for the SAME lease."""
    return f"ai_finding_router:dispatch:{workspace_id}:{specialist}"


def _enqueue(workspace_id, specialist: str, goal: str, agent_context: dict, performed_by, countdown: int) -> None:
    """Enqueue the specialist dispatch AFTER commit (celery-tasks §0) so the worker
    never races a finding row the caller's transaction hasn't committed yet."""
    from django.db import transaction

    from components.agents.infrastructure.tasks.agent_tasks import dispatch_finding_specialist

    args = [str(workspace_id), specialist, goal, agent_context, performed_by]
    if countdown:
        # Only the debounced immediate path needs a scheduling option; the cadence
        # keeps the codebase's canonical ``.delay()`` enqueue.
        transaction.on_commit(lambda: dispatch_finding_specialist.apply_async(args=args, countdown=countdown))
    else:
        transaction.on_commit(lambda: dispatch_finding_specialist.delay(*args))


def request_specialist_dispatch(
    workspace_id,
    specialist: str,
    *,
    source_type: str,
    trigger: str,
    performed_by: str | None = None,
    countdown: int = IMMEDIATE_DEBOUNCE_SECONDS,
) -> bool:
    """Dispatch *specialist* for this workspace NOW (debounced), if allowed.

    The immediate half of Henry's ask: a finding must not sit in an unexplained gap
    between "detected" and "fix proposed". Called per raised finding, so every step
    before the lease is O(1) — no query, no fan-out. Returns True when a dispatch
    was enqueued.
    """
    if not is_routable(source_type, specialist):
        return False
    if not ai_dispatch_allowed(workspace_id):
        logger.info(
            "immediate_dispatch_gated workspace_id=%s specialist=%s trigger=%s",
            workspace_id,
            specialist,
            trigger,
        )
        return False
    if not acquire_dispatch_lease(workspace_id, specialist):
        # A dispatch for this specialist is already in flight (this is what makes a
        # 500-finding scan ONE run, and what stops the cadence double-firing).
        logger.info(
            "immediate_dispatch_in_flight workspace_id=%s specialist=%s trigger=%s",
            workspace_id,
            specialist,
            trigger,
        )
        return False

    _enqueue(
        workspace_id,
        specialist,
        build_specialist_goal(),
        build_agent_context(specialist, source=trigger),
        performed_by,
        countdown,
    )
    logger.info(
        "immediate_dispatch_enqueued workspace_id=%s specialist=%s source_type=%s trigger=%s countdown=%s",
        workspace_id,
        specialist,
        source_type,
        trigger,
        countdown,
    )
    return True


def stamp_dispatch_in_flight(workspace_id, specialist: str, *, trigger: str, task_ids=None) -> int:
    """Mark the cards a starting dispatch is about to process as DRAFTING.

    The HUD must be able to say "drafting your fix now" from REAL data, not from a
    guess. The alternative — inferring it from the cache lease — would be a
    workspace-wide signal (every finding for the specialist flips at once) and would
    vanish on a cache eviction. Stamping the rows makes the state per-finding,
    durable, and visible in the API response like every other finding fact.

    ONE bulk write, no per-row query. ``triaged_at`` supersedes it: the triage stamp
    is what the reader checks first, so a stale ``triage_dispatch`` can never mask a
    finished fix. A stamp older than ``DISPATCH_STAMP_TTL_SECONDS`` is treated as
    stale by the reader (the run died) and the finding honestly falls back to QUEUED.

    Fail-safe: any error is logged and returns 0 — a progress stamp must never fail
    the dispatch it is describing.
    """
    from django.utils import timezone

    from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
        not_triaged_filter,
    )
    from infrastructure.persistence.project.models import Task

    try:
        qs = Task.objects.filter(
            workspace_id=workspace_id,
            source_type__in=ROUTABLE_SOURCE_TYPES,
            metadata__agent_type=specialist,
        ).filter(not_triaged_filter())
        if task_ids is not None:
            qs = qs.filter(id__in=[str(t) for t in task_ids])

        stamp = {
            "state": TriageState.DRAFTING.value,
            "specialist": specialist,
            "trigger": trigger,
            "at": timezone.now().isoformat(),
        }
        # Two queries total regardless of how many cards a scan filed (performance
        # rule §1): one read of the ids + metadata, one bulk write. A JSON-merge
        # UPDATE would be one query but has no portable expression across Postgres
        # and the SQLite the test settings run on.
        rows = list(qs.only("id", "metadata"))
        for row in rows:
            meta = row.metadata or {}
            meta["triage_dispatch"] = stamp
            row.metadata = meta
        if rows:
            Task.objects.bulk_update(rows, ["metadata"], batch_size=200)
        logger.info(
            "dispatch_stamped_in_flight workspace_id=%s specialist=%s trigger=%s cards=%s",
            workspace_id,
            specialist,
            trigger,
            len(rows),
        )
        return len(rows)
    except Exception:
        logger.exception(
            "dispatch_stamp_failed workspace_id=%s specialist=%s trigger=%s",
            workspace_id,
            specialist,
            trigger,
        )
        return 0


def draft_fix_lease_key(workspace_id, task_id) -> str:
    """Per-FINDING lease for the operator's button.

    Deliberately keyed per finding, not per specialist like the batch lease. Reusing
    the ``(workspace, specialist)`` key here would make the button silently no-op
    whenever an unrelated background dispatch happened to be running — a dead click,
    which is precisely the confusion this work removes. Same primitive, same TTL
    discipline, correct granularity. Double-opening a PR is independently impossible:
    ``OpenDraftPrUseCase`` short-circuits on an existing ``payload.draft_pr`` and the
    per-repo SAST throttle caps the rest.
    """
    return f"ai_finding_router:draft_fix:{workspace_id}:{task_id}"


def request_draft_fix(workspace_id, task_id, *, performed_by: str) -> dict:
    """Start the operator's "draft a fix PR" action for one finding. Never blocks.

    The controller stays thin: this holds the gate stack, the double-click lease, the
    optimistic DRAFTING stamp, and the enqueue. Raises :class:`DraftFixRefused` with
    a machine-readable reason the controller maps to a status — an operator gets a
    reason, never a dead click.
    """
    from infrastructure.persistence.project.models import Task

    card = Task.objects.filter(id=task_id, workspace_id=workspace_id).only("id", "source_type", "metadata").first()
    if card is None:
        raise DraftFixRefused("finding_not_found", "No such finding on this workspace's board.")

    meta = card.metadata or {}
    specialist = str(meta.get("agent_type") or "").strip()
    if not is_routable(card.source_type or "", specialist):
        raise DraftFixRefused(
            "not_routable",
            "This finding has no automated fix path — it is operator-reading material, not a code fix.",
        )
    # The artifact must MATCH the remediation target: a finding with no linked
    # repository (a public/unlinked container image, a cloud resource) has
    # nothing to open a PR against — its fix ships as a snippet/guidance on the
    # finding itself. Refusing HERE (typed, before any dispatch) replaces the
    # old doomed path: a full specialist run burned, then the engine refusing
    # the PR as a misleading ``finding_not_found``.
    if remediation_target(card.source_type or "", meta.get("payload") or {}) != TARGET_REPO:
        raise DraftFixRefused(
            "no_repo_target",
            "This finding's remediation target is not a connected repository — there is "
            "nothing to open a pull request against. The fix ships as guidance/a snippet "
            "on the finding, refreshed on each triage pass.",
        )
    if get_draft_pr(meta).get("url"):
        raise DraftFixRefused("draft_pr_exists", "A draft PR is already open for this finding.")
    if not ai_dispatch_allowed(workspace_id):
        raise DraftFixRefused(
            "ai_unavailable",
            "AI is turned off for this workspace (or halted by the operator kill switch).",
        )
    if not _acquire(draft_fix_lease_key(workspace_id, task_id), DRAFT_FIX_LEASE_SECONDS):
        # Already running — report it as success-in-flight, not an error: the operator
        # gets the same DRAFTING state either way, which is the honest answer.
        return {"state": TriageState.DRAFTING.value, "already_in_flight": True}

    stamp_dispatch_in_flight(workspace_id, specialist, trigger="on_demand", task_ids=[task_id])
    _enqueue_draft_fix(workspace_id, task_id, performed_by)
    logger.info(
        "draft_fix_requested workspace_id=%s task_id=%s specialist=%s performed_by=%s",
        workspace_id,
        task_id,
        specialist,
        performed_by,
    )
    return {"state": TriageState.DRAFTING.value, "already_in_flight": False, "specialist": specialist}


def _acquire(key: str, ttl: int) -> bool:
    from django.core.cache import cache

    return bool(cache.add(key, "1", ttl))


def _enqueue_draft_fix(workspace_id, task_id, performed_by: str) -> None:
    from django.db import transaction

    from components.agents.infrastructure.tasks.agent_tasks import draft_fix_for_finding

    transaction.on_commit(lambda: draft_fix_for_finding.delay(str(workspace_id), str(task_id), str(performed_by)))


def dispatch_pending_findings(workspace_id, *, performed_by: str | None = None, trigger: str = "ai_findings.route"):
    """Group this workspace's un-triaged routable findings by declared specialist and
    dispatch each group — the CADENCE path (and the backstop for anything the
    immediate path missed).

    Returns ``{specialist: pending_count}`` for the groups actually enqueued.
    """
    from collections import defaultdict

    from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
        not_triaged_filter,
    )
    from infrastructure.persistence.project.models import Task

    by_specialist: dict[str, int] = defaultdict(int)
    pending = (
        Task.objects.filter(workspace_id=workspace_id, source_type__in=ROUTABLE_SOURCE_TYPES)
        .filter(not_triaged_filter())
        .only("id", "metadata")
    )
    for task in pending:
        target = ((task.metadata or {}).get("agent_type") or "").strip()
        if target in NON_SPECIALIST:
            continue
        by_specialist[target] += 1

    enqueued: dict[str, int] = {}
    for specialist, count in by_specialist.items():
        if not acquire_dispatch_lease(workspace_id, specialist):
            logger.info(
                "ai_finding_router dispatch in-flight, skipping workspace=%s specialist=%s",
                workspace_id,
                specialist,
            )
            continue
        _enqueue(
            workspace_id,
            specialist,
            build_specialist_goal(count),
            build_agent_context(specialist, source=trigger),
            performed_by,
            countdown=0,
        )
        enqueued[specialist] = count
        logger.info(
            "ai_finding_router enqueued workspace=%s specialist=%s pending=%s",
            workspace_id,
            specialist,
            count,
        )
    return enqueued


class FindingDispatchAdapter(FindingDispatchPort):
    """Driven adapter exposing this engine through the agents context's port.

    Thin by design — the choreography stays in the module-level functions the
    cadence and the board handler already call, so all three triggers keep sharing
    ONE engine rather than the port becoming a fourth path.
    """

    def request_draft_fix(self, *, workspace_id: str, task_id: str, performed_by: str) -> dict:
        return request_draft_fix(workspace_id, task_id, performed_by=performed_by)
