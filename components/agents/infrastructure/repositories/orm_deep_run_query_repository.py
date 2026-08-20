"""ORM adapter that reads ``DeepRun`` + ``DeepRunLog`` for the deep-run observability API.

Progress is derived from the run's ``state`` JSON:

- ``state["plan"]["tasks"]`` gives the total task count
- ``state["completed_tasks"]`` gives the completed count

Sub-agent views are aggregated from the event log:  the worker-level
events (``worker_started``, ``worker_completed``, ``worker_failed``,
``worker_blocked``) carry a ``task_id`` in their payload, and we roll up
each task by its most recent event.  Tool calls come from the same log,
filtered by ``tool_name`` being non-empty.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from django.db.models import Count

from components.agents.application.ports.deep_run_query_port import (
    DeepRunEventView,
    DeepRunQueryPort,
    DeepRunSnapshotView,
    DeepRunStageView,
    DeepRunStatsView,
    DeepRunSubagentView,
    DeepRunSummaryView,
)


def _task_count(state) -> int:
    if not isinstance(state, dict):
        return 0
    plan = state.get("plan") or {}
    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    return len(tasks) if isinstance(tasks, list) else 0


def _completed_count(state) -> int:
    if not isinstance(state, dict):
        return 0
    completed = state.get("completed_tasks") or []
    return len(completed) if isinstance(completed, list) else 0


def _progress_percent(state) -> int:
    total = _task_count(state)
    if total <= 0:
        return 0
    done = _completed_count(state)
    return min(100, int(round(done / total * 100)))


# ── Redacted 5-stage pipeline projection ─────────────────────────────
#
# The SOC remediation loop, in order. Labels are display strings; keys
# are stable identifiers. This projection carries ONLY the stage identity
# + state + the current tool/agent NAMES — never prompt text or tool
# inputs/outputs (those stay owner-only behind retrieve/events).
_STAGE_DEFS = (
    ("alert", "Alert"),
    ("triage", "Triage"),
    ("finding", "Finding"),
    ("draft_pr", "Draft PR"),
    ("board", "Board Task"),
)
_TRIAGE_WRITE_TOOLS = {"triage_finding", "triage_cloud_exposure", "triage_container_vuln"}
_DRAFT_PR_TOOLS = {"open_draft_pr"}
_BOARD_TOOLS = {"assign_task"}


def _is_triage_log(log) -> bool:
    agent = (log.agent_type or "").lower()
    tool = log.tool_name or ""
    return "triage" in agent or log.event_type == "worker_started" or tool.startswith("list_pending")


def _stage_of_log(log) -> int:
    """Furthest pipeline stage a single log evidences (-1 = none).

    Reads only non-sensitive scalar columns (``event_type``, ``status``,
    ``agent_type``, ``tool_name``) — never ``payload``.
    """
    tool = log.tool_name or ""
    if tool in _DRAFT_PR_TOOLS:
        return 3
    if tool in _BOARD_TOOLS:
        return 4
    if tool in _TRIAGE_WRITE_TOOLS:
        return 2
    if _is_triage_log(log):
        return 1
    if log.event_type in ("run_completed", "worker_completed"):
        return 4
    if log.event_type == "run_started":
        return 0
    return -1


def _stage_projection(run, logs):
    """Derive (current_stage, current_agent, current_tool, stages) for a run.

    ``logs`` must be chronological. A completed run marks every lane
    ``done``; otherwise the furthest-reached lane is ``active``, earlier
    lanes ``done``, later lanes ``pending``. ``current_agent``/
    ``current_tool`` are the most-recent non-empty NAMES seen — no IO.
    """
    reached = 0
    current_agent = ""
    current_tool = ""
    for log in logs:
        stage = _stage_of_log(log)
        if stage > reached:
            reached = stage
        if log.agent_type:
            current_agent = log.agent_type
        if log.tool_name:
            current_tool = log.tool_name

    terminal_done = run.status == "completed"
    current_stage = len(_STAGE_DEFS) if terminal_done else reached
    stages = []
    for index, (key, label) in enumerate(_STAGE_DEFS):
        if terminal_done or index < current_stage:
            state = "done"
        elif index == current_stage:
            state = "active"
        else:
            state = "pending"
        stages.append(DeepRunStageView(key=key, label=label, state=state))
    return current_stage, current_agent, current_tool, tuple(stages)


def _summary_view(run, logs=()) -> DeepRunSummaryView:
    """Build the redacted, team-safe summary + pipeline projection.

    Only task COUNTS + status + the derived stage/agent/tool NAMES are
    exposed — ``goal`` (the raw user prompt) and all payload content are
    deliberately omitted so a non-owner teammate never reads run content.
    """
    state = run.state if isinstance(run.state, dict) else {}
    current_stage, current_agent, current_tool, stages = _stage_projection(run, logs)
    return DeepRunSummaryView(
        plan_id=run.plan_id,
        thread_id=run.thread_id,
        workspace_id=str(run.workspace_id) if run.workspace_id else None,
        status=run.status,
        progress_percent=_progress_percent(state),
        current_stage=current_stage,
        current_agent_type=current_agent,
        current_tool_name=current_tool,
        stages=stages,
        task_count=_task_count(state),
        completed_task_count=_completed_count(state),
        started_at=run.created_at,
        updated_at=run.updated_at,
        **_eval_fields(state, run),
    )


def _eval_fields(state: dict, run) -> dict:
    """Scalar eval signals — latency, tokens, priced cost, outcome, grading.

    Every field degrades to a neutral value when its key is absent or malformed.
    1,884 runs predate these keys, and a KeyError here would break the ENTIRE run
    list rather than one row: an observability surface that dies on old data is
    worse than one showing zeroes.

    Shapes are taken from what the telemetry ACTUALLY writes, verified against
    live rows on 2026-08-13 — ``cost_usd_records`` is a DICT keyed by an opaque
    id, not a list, and an earlier assumption that it was a list would have
    silently returned zeros for every run.

    ``rubric_verdicts`` is reduced to two COUNTS on purpose: a verdict is the
    grader's prose about the agent's output and can quote a finding's code, so it
    stays behind the owner-only reads.

    Those two counts were BOTH WRONG until 2026-08-20: this reader looked for a
    boolean under ``"satisfied"`` / ``"passed"``, while the writer has always
    stamped a tri-state STRING under ``"verdict"``
    (``deep/rubric.py::summarize_rubric_evaluations``). Nothing matched, so
    ``rubric_pass_count`` was 0 for every run ever graded and ``rubric_fail_count``
    equalled the verdict count — our only judge reporting 100% failure, invisibly,
    because zero is a plausible-looking number (ADR 0032 §1.3.2 / D12). The
    vocabulary now lives in ONE place
    (``domain/value_objects/rubric_verdict.py``) so writer and reader cannot
    disagree again.
    """
    from components.agents.domain.services.llm_pricing import price_run
    from components.agents.domain.value_objects.rubric_verdict import (
        is_rubric_graded,
        is_rubric_pass,
    )

    meta = state.get("run_metadata") if isinstance(state, dict) else None
    meta = meta if isinstance(meta, dict) else {}

    cost = price_run(meta.get("cost_usd_records"))

    goal_met = meta.get("goal_met")
    if not isinstance(goal_met, bool):
        goal_met = None  # unknown is NOT failed — never imply a verdict we lack

    try:
        iterations = int(meta.get("iteration_count") or 0)
    except (TypeError, ValueError):
        iterations = 0

    # Verdicts appear as a list on some runs and are absent on most (the rubric
    # only grades CRITIC_ENABLED_AGENTS, and only since it was switched on). A
    # dict-of-verdicts is tolerated too rather than assumed away.
    raw = meta.get("rubric_verdicts")
    if isinstance(raw, dict):
        verdicts = list(raw.values())
    elif isinstance(raw, (list, tuple)):
        verdicts = list(raw)
    else:
        verdicts = []
    passed = failed = 0
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        verdict = v.get("verdict")
        if not is_rubric_graded(verdict):
            # UNGRADED is not a failure. A stamp that carries no verdict string
            # (a middleware error, a shape we don't know) counts toward neither
            # side — absence is its own state, and the way to see it is that
            # pass + fail is less than the number of stamps (ADR 0032 D4).
            continue
        if is_rubric_pass(verdict):
            passed += 1
        else:
            failed += 1

    try:
        duration_ms = max(0, int((run.updated_at - run.created_at).total_seconds() * 1000))
    except (TypeError, AttributeError):
        duration_ms = 0

    return {
        "duration_ms": duration_ms,
        "input_tokens": cost.input_tokens,
        "output_tokens": cost.output_tokens,
        "llm_calls": cost.llm_calls,
        "models": cost.models,
        "cost_usd": cost.cost_usd,
        "priced": cost.priced,
        "price_table_version": cost.price_table_version,
        "goal_met": goal_met,
        "iteration_count": iterations,
        "rubric_pass_count": passed,
        "rubric_fail_count": failed,
    }


def _event_view(log_row) -> DeepRunEventView:
    return DeepRunEventView(
        id=log_row.id,
        timestamp=log_row.created_at,
        event_type=log_row.event_type,
        status=log_row.status or "",
        agent_type=log_row.agent_type or "",
        tool_name=log_row.tool_name or "",
        payload=log_row.payload or {},
    )


_WORKER_TERMINAL_STATES = {
    "worker_completed": "completed",
    "worker_failed": "failed",
    "worker_blocked": "blocked",
}

#: ADR 0031 D2 — the run outcomes a ``worker_completed`` row may now carry.
#: Before D2 the row was written with ``status="completed"`` no matter what the
#: worker reported, so a sub-agent whose every tool call failed still read as a
#: clean completion in the run trace. Anything else on the row (a legacy blank,
#: or the ``"denied"`` a ``worker_blocked`` row carries as its *reason*) falls
#: back to the event-type map, which is what those events mean.
_WORKER_COMPLETED_OUTCOMES = frozenset({"completed", "partial", "failed"})


def _worker_terminal_status(row) -> str:
    """The sub-agent status for a terminal worker event."""
    if row.event_type == "worker_completed" and (row.status or "") in _WORKER_COMPLETED_OUTCOMES:
        return row.status
    return _WORKER_TERMINAL_STATES[row.event_type]


def _subagent_views(logs: Iterable) -> tuple[DeepRunSubagentView, ...]:
    """Roll up worker events into per-task sub-agent views.

    A task is identified by ``payload["task_id"]``.  We track the first
    ``worker_started`` as ``started_at`` and the first terminal event as
    ``completed_at``.  Tool calls are collected from rows with a
    non-empty ``tool_name`` tagged with the same ``task_id`` (or no
    task_id, in which case they fall under the most recent task).
    """
    started_at: dict[str, datetime] = {}
    completed_at: dict[str, datetime] = {}
    status: dict[str, str] = {}
    agent_type: dict[str, str] = {}
    tool_calls: dict[str, list[dict]] = defaultdict(list)

    ordered = sorted(logs, key=lambda row: row.created_at)
    last_task_id: str | None = None

    for row in ordered:
        payload = row.payload or {}
        task_id = str(payload.get("task_id") or "")
        if task_id:
            last_task_id = task_id

        if row.event_type == "worker_started" and task_id:
            started_at.setdefault(task_id, row.created_at)
            status[task_id] = "running"
            if row.agent_type:
                agent_type[task_id] = row.agent_type

        elif row.event_type in _WORKER_TERMINAL_STATES and task_id:
            completed_at.setdefault(task_id, row.created_at)
            status[task_id] = _worker_terminal_status(row)
            if row.agent_type and task_id not in agent_type:
                agent_type[task_id] = row.agent_type

        if row.tool_name:
            bucket = task_id or last_task_id or ""
            if bucket:
                tool_calls[bucket].append(
                    {
                        "tool_name": row.tool_name,
                        "agent_type": row.agent_type or "",
                        "status": row.status or "",
                        "timestamp": row.created_at.isoformat(),
                    }
                )

    task_ids = sorted(
        set(started_at) | set(completed_at) | set(status) | set(tool_calls),
        key=lambda tid: started_at.get(tid, datetime.max),
    )
    views: list[DeepRunSubagentView] = []
    for task_id in task_ids:
        views.append(
            DeepRunSubagentView(
                task_id=task_id,
                agent_type=agent_type.get(task_id, ""),
                status=status.get(task_id, "unknown"),
                started_at=started_at.get(task_id),
                completed_at=completed_at.get(task_id),
                tool_calls=tuple(tool_calls.get(task_id, ())),
            )
        )
    return tuple(views)


class OrmDeepRunQueryRepository(DeepRunQueryPort):
    """Reads from ``DeepRun`` + ``DeepRunLog`` ORM models."""

    def get_snapshot(self, plan_id: str) -> DeepRunSnapshotView | None:
        from infrastructure.persistence.ai.agents.models import DeepRun

        run = (
            DeepRun.objects.filter(plan_id=plan_id).select_related("workspace", "user").order_by("-updated_at").first()
        )
        if run is None:
            return None

        logs = list(run.logs.all().order_by("created_at"))
        state = run.state if isinstance(run.state, dict) else {}
        plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
        run_metadata = state.get("run_metadata") if isinstance(state.get("run_metadata"), dict) else {}

        return DeepRunSnapshotView(
            plan_id=run.plan_id,
            thread_id=run.thread_id,
            workspace_id=str(run.workspace_id) if run.workspace_id else None,
            user_id=str(run.user_id),
            status=run.status,
            progress_percent=_progress_percent(state),
            goal=str(plan.get("goal") or run_metadata.get("goal") or ""),
            agent_type=str(run_metadata.get("agent_type") or ""),
            task_count=_task_count(state),
            completed_task_count=_completed_count(state),
            started_at=run.created_at,
            updated_at=run.updated_at,
            last_error=run.last_error or "",
            subagents=_subagent_views(logs),
        )

    def list_runs(
        self,
        *,
        workspace_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> list[DeepRunSummaryView]:
        from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog

        queryset = DeepRun.objects.filter(workspace_id=workspace_id).order_by("-updated_at")
        if status:
            queryset = queryset.filter(status=status)
        runs = list(queryset[:limit])
        if not runs:
            return []

        # One query for all the page's logs, deliberately loading ONLY the
        # non-sensitive scalar columns the stage projection reads — never
        # ``payload`` (which carries tool inputs/outputs). This keeps the
        # redaction airtight at the data-access layer AND bounds the cost
        # to 2 queries regardless of ``limit``.
        run_ids = [run.id for run in runs]
        logs_by_run: dict = defaultdict(list)
        log_rows = (
            DeepRunLog.objects.filter(deep_run_id__in=run_ids)
            .only("deep_run_id", "event_type", "status", "agent_type", "tool_name", "created_at")
            .order_by("created_at")
        )
        for log in log_rows:
            logs_by_run[log.deep_run_id].append(log)

        return [_summary_view(run, logs_by_run.get(run.id, ())) for run in runs]

    def list_events(
        self,
        plan_id: str,
        *,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[DeepRunEventView]:
        from infrastructure.persistence.ai.agents.models import DeepRun

        run = DeepRun.objects.filter(plan_id=plan_id).order_by("-updated_at").first()
        if run is None:
            return []

        queryset = run.logs.all().order_by("created_at")
        if since is not None:
            queryset = queryset.filter(created_at__gt=since)
        return [_event_view(row) for row in queryset[:limit]]

    def get_workspace_stats(
        self, workspace_id: str | None = None, *, since: datetime | None = None
    ) -> DeepRunStatsView:
        from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog

        runs_qs = DeepRun.objects.all()
        logs_qs = DeepRunLog.objects.all()
        if workspace_id is not None:
            runs_qs = runs_qs.filter(workspace_id=workspace_id)
            logs_qs = logs_qs.filter(deep_run__workspace_id=workspace_id)
        if since is not None:
            runs_qs = runs_qs.filter(created_at__gte=since)
            logs_qs = logs_qs.filter(created_at__gte=since)

        total_runs = runs_qs.count()
        runs_by_status = {row["status"]: row["n"] for row in runs_qs.values("status").annotate(n=Count("id"))}
        failed = runs_by_status.get("failed", 0)
        failure_rate = (failed / total_runs) if total_runs else 0.0

        agent_type_counts: dict[str, int] = defaultdict(int)
        for row in runs_qs.values_list("state", flat=True):
            if not isinstance(row, dict):
                continue
            meta = row.get("run_metadata") if isinstance(row.get("run_metadata"), dict) else {}
            slug = str(meta.get("agent_type") or "")
            if slug:
                agent_type_counts[slug] += 1

        tool_call_counts = {
            row["tool_name"]: row["n"]
            for row in (logs_qs.exclude(tool_name="").values("tool_name").annotate(n=Count("id")).order_by("-n")[:50])
        }

        window_started_at = since or (runs_qs.order_by("created_at").values_list("created_at", flat=True).first())

        return DeepRunStatsView(
            workspace_id=workspace_id,
            total_runs=total_runs,
            runs_by_status=runs_by_status,
            runs_by_agent_type=dict(agent_type_counts),
            tool_call_counts=tool_call_counts,
            failure_rate=round(failure_rate, 4),
            window_started_at=window_started_at,
        )
