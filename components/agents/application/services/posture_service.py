"""Security-posture query service — deterministic aggregation, no LLM.

The single posture fact store the posture surfaces read (vision doc
``docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md`` §1 design rule: ONE fact
store, MULTIPLE lenses). Every number this module returns is computed from
rows that already exist — board findings (``project.Task``), deep-run
telemetry (``DeepRun`` / its ``state.run_metadata``), the ``run_telemetry``
stamps specialists leave on handled findings, and human votes
(``AgentResponseFeedback``). Nothing here calls a model; the LLM in
``posture_agent`` only narrates what these functions return.

Hard rules (vision §2 + §8, enforced by tests):

* **No composite "posture score"** — components only. Suppressing findings
  must never be able to *raise* a number here.
* **Medians, not means** — response-time KPIs use medians for outlier
  resistance, reported against industry bands per severity.
* **Every claim carries its evidence** — ids and counts ride alongside every
  aggregate; missing data is explicit (``no_data`` flags / nulls), never
  invented.

Module style mirrors ``detector_cycle.py``: framework-free where possible
(pure ``compute_*`` functions are stdlib-only and unit-testable without a DB);
the public ``*_posture`` / ``*_kpis`` / ``*_health`` / ``*_outlook`` entry
points do their ORM reads through lazy imports.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Industry response-time bands per severity, in hours — MTTR-by-severity
# benchmarks per "Prophet Security SOC metrics benchmarks" (critical 1h,
# high 2h, medium 4h, low 8h). Reported next to every median so the reader
# sees the yardstick, never a bare number.
RESPONSE_BANDS_HOURS: dict[str, float] = {
    "critical": 1.0,
    "high": 2.0,
    "medium": 4.0,
    "low": 8.0,
}
BENCHMARK_SOURCE = "Prophet Security SOC metrics benchmarks"

# The posture report's own board card — excluded from every aggregate so the
# weekly report can never count (or inflate) itself.
POSTURE_REPORT_SOURCE_TYPE = "ai.posture_report"

_SEVERITY_ORDER = ("critical", "high", "medium", "low")
_MAX_SAMPLE_IDS = 10

PERSONA_ENGINEER = "engineer"
PERSONA_EXECUTIVE = "executive"
PERSONAS = (PERSONA_ENGINEER, PERSONA_EXECUTIVE)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _median(values: list[float]) -> float | None:
    """Median of a list (outlier-resistant, vision §2). ``None`` when empty."""
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO timestamp defensively; naive values are assumed UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    # Normalize BOTH ends through _parse_iso — live rows mix aware DB
    # datetimes with naive ones (Task.metadata timestamps are written with
    # datetime.now().isoformat()), and a naive-aware subtraction raises
    # TypeError. Test fixtures were uniformly aware, which is why this only
    # surfaced in the live posture-chat verification (2026-07-21).
    start = _parse_iso(start)
    end = _parse_iso(end)
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds() / 3600.0
    return delta if delta >= 0 else None


def _severity_of(row: dict[str, Any]) -> str:
    sev = str(row.get("severity") or "").strip().lower()
    return sev if sev in RESPONSE_BANDS_HOURS else "unknown"


def _is_open(row: dict[str, Any]) -> bool:
    return row.get("status") == "todo" and row.get("triage_status") != "triaged"


# ── Pure computations (stdlib only — no ORM, no Django) ─────────────────────


def compute_findings_posture(rows: list[dict[str, Any]], *, now: datetime, window_days: int) -> dict[str, Any]:
    """Classify finding rows into the open/backlog/toil posture aggregate.

    Args:
        rows: one dict per board finding (deduped by id):
            ``{"id": str, "severity": str, "kind": str (source_type),
               "status": "todo"|"done"|"archived",
               "created_at": datetime,
               "triage_status": str|None, "triaged_at": iso str|None,
               "needs_human": bool}``
        now: aggregation instant (windows measured backwards from here).
        window_days: flow window for triaged counts + toil split. Stocks
            (open findings, needs-human backlog, oldest untriaged age) are
            measured at ``now`` and are NOT windowed — a backlog is a stock.

    Every count ships evidence (sample ids); empty data → zeros + ``no_data``.
    """
    window_start = now - timedelta(days=window_days)
    day_ago = now - timedelta(hours=24)

    open_rows = [r for r in rows if _is_open(r)]
    by_severity: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for row in open_rows:
        by_severity[_severity_of(row)] = by_severity.get(_severity_of(row), 0) + 1
        kind = str(row.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1

    oldest_untriaged_age_hours: float | None = None
    oldest_untriaged_id: str | None = None
    for row in open_rows:
        age = _hours_between(row.get("created_at"), now)
        if age is not None and (oldest_untriaged_age_hours is None or age > oldest_untriaged_age_hours):
            oldest_untriaged_age_hours = age
            oldest_untriaged_id = str(row.get("id"))

    # needs-human backlog: handled-but-escalated cards still open on the board
    # — the queue a human must work through. A stock, measured now.
    needs_human_rows = [
        r for r in rows if r.get("status") == "todo" and r.get("triage_status") == "triaged" and r.get("needs_human")
    ]

    # Triaged flows, from the triage stamp's own timestamp (not updated_at).
    triaged_rows = [r for r in rows if r.get("triage_status") == "triaged" and _parse_iso(r.get("triaged_at"))]
    triaged_in_window = [r for r in triaged_rows if _parse_iso(r["triaged_at"]) >= window_start]
    triaged_24h = [r for r in triaged_in_window if _parse_iso(r["triaged_at"]) >= day_ago]

    # Toil split over the window's handled findings: what the agents absorbed
    # vs. what they escalated to a human (vision §2 — quantify absorbed toil).
    auto_triaged = [r for r in triaged_in_window if not r.get("needs_human")]
    escalated = [r for r in triaged_in_window if r.get("needs_human")]
    handled_total = len(triaged_in_window)
    absorption_rate = round(len(auto_triaged) / handled_total, 4) if handled_total else None

    no_data = not rows

    return {
        "window_days": window_days,
        "computed_at": now.isoformat(),
        "open_findings": {
            "total": len(open_rows),
            "by_severity": by_severity,
            "by_kind": by_kind,
            "sample_task_ids": [str(r["id"]) for r in open_rows[:_MAX_SAMPLE_IDS]],
        },
        "needs_human_backlog": {
            "count": len(needs_human_rows),
            "sample_task_ids": [str(r["id"]) for r in needs_human_rows[:_MAX_SAMPLE_IDS]],
        },
        "oldest_untriaged_age_hours": (
            round(oldest_untriaged_age_hours, 2) if oldest_untriaged_age_hours is not None else None
        ),
        "oldest_untriaged_task_id": oldest_untriaged_id,
        "triaged": {"last_24h": len(triaged_24h), "last_window": len(triaged_in_window)},
        "toil": {
            "handled_total": handled_total,
            "auto_triaged": len(auto_triaged),
            "escalated_to_human": len(escalated),
            "auto_absorption_rate": absorption_rate,
        },
        "no_data": no_data,
    }


def compute_response_kpis(triaged_rows: list[dict[str, Any]], *, window_days: int) -> dict[str, Any]:
    """Median response-time KPIs per severity, against the industry bands.

    Args:
        triaged_rows: findings handled inside the window:
            ``{"id", "severity", "created_at": datetime,
               "triaged_at": iso str|datetime,
               "first_action_at": iso str|datetime|None}``
            ``first_action_at`` is the first provenance event AFTER filing
            (an agent picked the card up) — the acknowledgment proxy.

    Medians, not means (outlier resistance). Rows with an unknown severity
    are excluded from per-severity medians (never guessed into a band) but
    still count toward acknowledgment latency.
    """
    latencies_by_severity: dict[str, list[float]] = {}
    ack_latencies: list[float] = []
    for row in triaged_rows:
        created = row.get("created_at")
        triaged = _parse_iso(row.get("triaged_at"))
        latency = _hours_between(created, triaged)
        if latency is not None:
            sev = _severity_of(row)
            if sev in RESPONSE_BANDS_HOURS:
                latencies_by_severity.setdefault(sev, []).append(latency)
        ack = _hours_between(created, _parse_iso(row.get("first_action_at")))
        if ack is not None:
            ack_latencies.append(ack)

    per_severity: dict[str, dict[str, Any]] = {}
    for sev in _SEVERITY_ORDER:
        band = RESPONSE_BANDS_HOURS[sev]
        values = latencies_by_severity.get(sev, [])
        med = _median(values)
        per_severity[sev] = {
            "median_hours": round(med, 2) if med is not None else None,
            "band_hours": band,
            "within_band": (med <= band) if med is not None else None,
            "sample_count": len(values),
            "no_data": not values,
        }

    ack_median = _median(ack_latencies)
    return {
        "window_days": window_days,
        "triage_latency_by_severity": per_severity,
        "acknowledgment_latency": {
            "median_hours": round(ack_median, 2) if ack_median is not None else None,
            "sample_count": len(ack_latencies),
            "no_data": not ack_latencies,
        },
        "benchmark_source": BENCHMARK_SOURCE,
        "no_data": not triaged_rows,
    }


def compute_fleet_health(
    run_rows: list[dict[str, Any]],
    handled_rows: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    *,
    window_days: int,
) -> dict[str, Any]:
    """Fleet health: run outcomes, rubric verdicts, spend, human votes, toil.

    Args:
        run_rows: ``{"id", "status", "cost_records": [ {"cost_usd": float|None}, ... ]}``
            per DeepRun in the window (``cost_records`` from
            ``state.run_metadata.cost_usd_records``).
        handled_rows: ``{"id", "agent", "rubric_verdict": str|None}`` per
            finding handled in the window (verdict from
            ``metadata.run_telemetry.rubric_verdicts.verdict``; ``None`` =
            not graded — excluded from the pass-rate denominator, never
            counted as a pass).
        feedback_rows: ``{"rating": "up"|"down"}`` per human vote in window.
    """
    completed = sum(1 for r in run_rows if r.get("status") == "completed")
    failed = sum(1 for r in run_rows if r.get("status") == "failed")
    in_flight = len(run_rows) - completed - failed
    terminal = completed + failed
    success_rate = round(completed / terminal, 4) if terminal else None

    total_cost = 0.0
    priced = 0
    unpriced = 0
    for run in run_rows:
        for record in run.get("cost_records") or []:
            cost = record.get("cost_usd") if isinstance(record, dict) else None
            if isinstance(cost, (int, float)):
                total_cost += float(cost)
                priced += 1
            else:
                unpriced += 1

    verdict_counts: dict[str, int] = {}
    graded = 0
    passed = 0
    for row in handled_rows:
        verdict = row.get("rubric_verdict")
        if not verdict:
            continue
        graded += 1
        verdict = str(verdict)
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        if verdict == "satisfied":
            passed += 1

    by_agent: dict[str, int] = {}
    for row in handled_rows:
        agent = str(row.get("agent") or "").strip() or "unknown"
        by_agent[agent] = by_agent.get(agent, 0) + 1

    up = sum(1 for r in feedback_rows if r.get("rating") == "up")
    down = sum(1 for r in feedback_rows if r.get("rating") == "down")
    votes = up + down

    return {
        "window_days": window_days,
        "deep_runs": {
            "total": len(run_rows),
            "completed": completed,
            "failed": failed,
            "in_flight": in_flight,
            "success_rate": success_rate,
            "no_data": not run_rows,
        },
        "rubric_verdicts": {
            "graded_total": graded,
            "by_verdict": verdict_counts,
            "pass_rate": round(passed / graded, 4) if graded else None,
            "no_data": not graded,
        },
        "cost": {
            "total_cost_usd": round(total_cost, 6),
            "cost_per_day_usd": round(total_cost / window_days, 6) if window_days else None,
            "priced_records": priced,
            "unpriced_records": unpriced,
            "no_data": (priced + unpriced) == 0,
        },
        "human_feedback": {
            "up": up,
            "down": down,
            "total": votes,
            "up_ratio": round(up / votes, 4) if votes else None,
            "no_data": not votes,
        },
        "dispatches": {
            "handled_findings": len(handled_rows),
            "by_agent": by_agent,
            "no_data": not handled_rows,
        },
    }


def compute_forward_outlook(
    *,
    findings_this_week: int,
    findings_last_week: int,
    escalations_this_week: int,
    escalations_last_week: int,
    needs_human_backlog: int,
) -> dict[str, Any]:
    """Week-over-week trend deltas. Simple honest arithmetic, no forecasting.

    ``direction`` reflects finding creation only; backlog growth is reported
    as its own delta. A percentage is only computed when last week has a
    non-zero base (never a fabricated ∞%).
    """
    delta = findings_this_week - findings_last_week
    pct = round(delta / findings_last_week, 4) if findings_last_week else None
    if delta > 0:
        direction = "rising"
    elif delta < 0:
        direction = "falling"
    else:
        direction = "flat"
    return {
        "findings_created": {
            "this_week": findings_this_week,
            "last_week": findings_last_week,
            "delta": delta,
            "pct_change": pct,
            "direction": direction,
        },
        "needs_human_escalations": {
            "this_week": escalations_this_week,
            "last_week": escalations_last_week,
            "delta": escalations_this_week - escalations_last_week,
        },
        "needs_human_backlog_now": needs_human_backlog,
        "no_data": (findings_this_week + findings_last_week + escalations_this_week + escalations_last_week) == 0,
    }


def _ctem_mapping(findings: dict[str, Any], fleet: dict[str, Any]) -> dict[str, str]:
    """State the CTEM stage mapping (Gartner: Scoping→Discovery→Prioritization→
    Validation→Mobilization) with this window's real numbers attached."""
    return {
        "discovery": (
            "log-watch + fleet detectors file evidence-bearing findings "
            f"({findings['open_findings']['total']} currently open)"
        ),
        "prioritization": ("severity + impact scoring on every finding (see open_findings.by_severity)"),
        "validation": (
            "grounded verification + rubric grading of every agent suggestion "
            f"({fleet['rubric_verdicts']['graded_total']} graded this window)"
        ),
        "mobilization": (
            "triage comments, board-card moves and draft-PR remediation "
            f"({findings['toil']['handled_total']} findings handled this window)"
        ),
    }


def compose_posture_report(
    persona: str,
    findings: dict[str, Any],
    kpis: dict[str, Any],
    fleet: dict[str, Any],
    outlook: dict[str, Any],
) -> dict[str, Any]:
    """Compose the four aggregates into one persona-framed report.

    SAME facts, different framing — the lens lives in this structure, never in
    LLM imagination (vision §1). ``engineer`` = full drill-down including
    finding ids; ``executive`` = NACD five-category board shape (threat
    environment / financial / maturity / forward-looking, vision §8
    adjustment 3) with the identical numbers and no per-finding ids.
    """
    from components.shared_kernel.domain.errors import ValidationError

    persona = (persona or PERSONA_ENGINEER).strip().lower()
    if persona not in PERSONAS:
        raise ValidationError(f"persona must be one of {PERSONAS}, got {persona!r}")

    ctem = _ctem_mapping(findings, fleet)
    if persona == PERSONA_ENGINEER:
        return {
            "persona": PERSONA_ENGINEER,
            "window_days": findings["window_days"],
            "ctem_mapping": ctem,
            "findings_posture": findings,
            "response_kpis": kpis,
            "fleet_health": fleet,
            "forward_outlook": outlook,
        }

    bands = {
        sev: {
            "median_hours": entry["median_hours"],
            "band_hours": entry["band_hours"],
            "within_band": entry["within_band"],
        }
        for sev, entry in kpis["triage_latency_by_severity"].items()
    }
    return {
        "persona": PERSONA_EXECUTIVE,
        "window_days": findings["window_days"],
        "ctem_mapping": ctem,
        "nacd_summary": {
            "threat_environment": {
                "open_findings_total": findings["open_findings"]["total"],
                "open_by_severity": findings["open_findings"]["by_severity"],
                "findings_trend": outlook["findings_created"],
            },
            "financial": {
                "total_cost_usd_window": fleet["cost"]["total_cost_usd"],
                "cost_per_day_usd": fleet["cost"]["cost_per_day_usd"],
                "cost_no_data": fleet["cost"]["no_data"],
            },
            "maturity": {
                "response_kpi_bands": bands,
                "benchmark_source": kpis["benchmark_source"],
                "rubric_pass_rate": fleet["rubric_verdicts"]["pass_rate"],
                "run_success_rate": fleet["deep_runs"]["success_rate"],
                "toil_auto_absorption_rate": findings["toil"]["auto_absorption_rate"],
            },
            "forward_looking": {
                "needs_human_backlog": findings["needs_human_backlog"]["count"],
                "needs_human_escalations": outlook["needs_human_escalations"],
                "oldest_untriaged_age_hours": findings["oldest_untriaged_age_hours"],
                "direction": outlook["findings_created"]["direction"],
            },
        },
        "no_data": findings["no_data"] and fleet["deep_runs"]["no_data"],
    }


# ── ORM-backed collectors (lazy imports, per detector_cycle conventions) ────


def _finding_row(task) -> dict[str, Any]:
    meta = task.metadata or {}
    triage = meta.get("triage") or {}
    telemetry = meta.get("run_telemetry") if isinstance(meta.get("run_telemetry"), dict) else {}
    rubric = telemetry.get("rubric_verdicts") if isinstance(telemetry.get("rubric_verdicts"), dict) else None

    # Acknowledgment proxy: the first provenance event AFTER the filing event
    # (an agent/human acted on the card). Filing itself is not an ack.
    first_action_at = None
    events = ((meta.get("provenance") or {}).get("events") or [])[1:]
    if events and isinstance(events[0], dict):
        first_action_at = events[0].get("at")

    return {
        "id": str(task.id),
        "severity": meta.get("severity") or "",
        "kind": task.source_type,
        "status": task.status,
        "created_at": task.created_at,
        "triage_status": triage.get("status"),
        "triaged_at": triage.get("triaged_at"),
        "needs_human": bool(triage.get("needs_human")),
        "agent": triage.get("agent") or "",
        "rubric_verdict": rubric.get("verdict") if rubric else None,
        "first_action_at": first_action_at,
    }


def _collect_finding_rows(workspace_id: str, window_start: datetime) -> list[dict[str, Any]]:
    """Board findings relevant to posture: every open card (stock) plus every
    card touched inside the window (flow candidates). Two querysets deduped by
    id — keeps this application module free of ``django.db.models`` imports
    (the purity rule bans framework imports here, even lazy ones); the pure
    functions do the precise classification off the triage stamp itself."""
    from infrastructure.persistence.project.models import Task

    base = (
        Task.objects.filter(workspace_id=workspace_id, source_type__startswith="ai.")
        .exclude(source_type=POSTURE_REPORT_SOURCE_TYPE)
        .only("id", "status", "source_type", "created_at", "metadata")
    )
    rows: dict[str, dict[str, Any]] = {}
    for queryset in (base.filter(status="todo"), base.filter(updated_at__gte=window_start)):
        for task in queryset.iterator(chunk_size=500):
            row = _finding_row(task)
            rows[row["id"]] = row
    return list(rows.values())


def _triaged_in_window(rows: list[dict[str, Any]], window_start: datetime) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        triaged_at = _parse_iso(row.get("triaged_at"))
        if row.get("triage_status") == "triaged" and triaged_at is not None and triaged_at >= window_start:
            out.append(row)
    return out


def findings_posture(workspace_id: str, window_days: int = 7) -> dict[str, Any]:
    """Open findings, needs-human backlog, triage flows and toil split."""
    now = _utc_now()
    rows = _collect_finding_rows(str(workspace_id), now - timedelta(days=window_days))
    return compute_findings_posture(rows, now=now, window_days=window_days)


def response_kpis(workspace_id: str, window_days: int = 7) -> dict[str, Any]:
    """Median created→triage latency per severity vs industry bands + ack latency."""
    now = _utc_now()
    window_start = now - timedelta(days=window_days)
    rows = _collect_finding_rows(str(workspace_id), window_start)
    return compute_response_kpis(_triaged_in_window(rows, window_start), window_days=window_days)


def fleet_health(workspace_id: str, window_days: int = 7) -> dict[str, Any]:
    """Deep-run success, rubric verdicts, spend, human votes, dispatch counts."""
    from infrastructure.persistence.ai.agents.models import DeepRun
    from infrastructure.persistence.ai.conversations.models import AgentResponseFeedback

    now = _utc_now()
    window_start = now - timedelta(days=window_days)

    run_rows: list[dict[str, Any]] = []
    runs = DeepRun.objects.filter(workspace_id=workspace_id, created_at__gte=window_start).only("id", "status", "state")
    for run in runs.iterator(chunk_size=500):
        state = run.state if isinstance(run.state, dict) else {}
        run_metadata = state.get("run_metadata") if isinstance(state.get("run_metadata"), dict) else {}
        cost_records = run_metadata.get("cost_usd_records")
        run_rows.append(
            {
                "id": str(run.id),
                "status": run.status,
                "cost_records": cost_records if isinstance(cost_records, list) else [],
            }
        )

    finding_rows = _collect_finding_rows(str(workspace_id), window_start)
    handled_rows = _triaged_in_window(finding_rows, window_start)

    # Conversation carries workspace only in metadata JSON (no FK) — same
    # traversal the AI quality rollup task uses.
    feedback_rows = [
        {"rating": rating}
        for rating in AgentResponseFeedback.objects.filter(
            created_at__gte=window_start,
            message__conversation__metadata__workspace_id=str(workspace_id),
        ).values_list("rating", flat=True)
    ]

    return compute_fleet_health(run_rows, handled_rows, feedback_rows, window_days=window_days)


def forward_outlook(workspace_id: str) -> dict[str, Any]:
    """This-week vs last-week deltas: finding creation + needs-human growth."""
    from infrastructure.persistence.project.models import Task

    now = _utc_now()
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    base = Task.objects.filter(workspace_id=workspace_id, source_type__startswith="ai.").exclude(
        source_type=POSTURE_REPORT_SOURCE_TYPE
    )
    findings_this_week = base.filter(created_at__gte=week_ago).count()
    findings_last_week = base.filter(created_at__gte=two_weeks_ago, created_at__lt=week_ago).count()

    rows = _collect_finding_rows(str(workspace_id), two_weeks_ago)
    escalations_this_week = 0
    escalations_last_week = 0
    for row in rows:
        if not row.get("needs_human") or row.get("triage_status") != "triaged":
            continue
        triaged_at = _parse_iso(row.get("triaged_at"))
        if triaged_at is None:
            continue
        if triaged_at >= week_ago:
            escalations_this_week += 1
        elif triaged_at >= two_weeks_ago:
            escalations_last_week += 1

    backlog_now = sum(
        1 for r in rows if r.get("status") == "todo" and r.get("triage_status") == "triaged" and r.get("needs_human")
    )

    return compute_forward_outlook(
        findings_this_week=findings_this_week,
        findings_last_week=findings_last_week,
        escalations_this_week=escalations_this_week,
        escalations_last_week=escalations_last_week,
        needs_human_backlog=backlog_now,
    )


def posture_report(workspace_id: str, persona: str = PERSONA_ENGINEER, window_days: int = 7) -> dict[str, Any]:
    """Compose all four aggregates into one persona-framed posture report."""
    return compose_posture_report(
        persona,
        findings_posture(workspace_id, window_days=window_days),
        response_kpis(workspace_id, window_days=window_days),
        fleet_health(workspace_id, window_days=window_days),
        forward_outlook(workspace_id),
    )
