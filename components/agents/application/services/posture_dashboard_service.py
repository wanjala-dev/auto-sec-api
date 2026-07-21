"""Posture-dashboard query service — deterministic composition, no LLM.

The HUD POSTURE module's single read model (vision doc
``docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md`` §1 + §5): ONE fact
store, MULTIPLE lenses, rendered as chart-ready daily series + the KPI
band table + the CTEM stage strip. This module composes EXISTING
aggregation services — it re-derives nothing:

- ``posture_service`` → findings posture, response-KPI bands, fleet
  health, forward outlook (persona-framed via
  ``compose_posture_report`` — same facts, different framing).
- ``ai_governance_service.ai_activity`` → runs by source + tool calls
  by risk tier (the AI-SPM activity summary).
- ``log_metrics_query_service.query_metric`` → log lines/day from the
  ``LogMetricBucket`` TOTAL_VOLUME rollups.
- ``AiActionDailyRollup`` rows (the ``ai.rollup_ai_action_daily`` beat
  task's read model) → cost/day + runs/day series. The dashboard reads
  ONLY the rollup — never the raw ``DeepRun``/``DeepRunLog`` tables.

Hard rules (vision §2 + §8, enforced by tests):

* **No composite "posture score"** — components only, ever.
* **Every surface is ACTION-LINKED** — each block carries a ``link``
  hint (``{"panel": ...}``) the frontend maps to a HUD panel deep link.
  A number with no drill destination is a graph wall; we don't ship it.
* **Missing data is explicit** — ``no_data`` flags and zero-filled
  calendar days, never invented values; projections are ``None`` when
  there is nothing to project from.

Module style mirrors ``posture_service``: pure ``compute_*`` functions
are stdlib-only and unit-testable without a DB; the public ``dashboard``
entry point does its ORM reads through lazy imports.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from components.agents.application.services import ai_governance_service, posture_service

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90

# Link hints — the frontend maps these onto HUD panel deep links
# (``?panel=<id>`` / ``setActivePanel``). Findings-shaped numbers drill
# into the triage board; fleet/run/cost numbers drill into the agents
# surface; log volume drills into the logs surface.
LINK_KANBAN = {"panel": "kanban"}
LINK_AGENTS = {"panel": "agents"}
LINK_LOGS = {"panel": "logs"}


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _window_dates(today: date, window_days: int) -> list[date]:
    """The window's calendar days, oldest first, ending today (inclusive)."""
    return [today - timedelta(days=offset) for offset in range(window_days - 1, -1, -1)]


# ── Pure computations (stdlib only — no ORM, no Django) ─────────────────────


def compute_daily_series(
    values_by_date: dict[str, float | int],
    *,
    today: date,
    window_days: int,
    link: dict[str, str],
    round_to: int | None = None,
) -> dict[str, Any]:
    """Zero-fill a per-day mapping into a chart-ready points series.

    ``values_by_date`` maps ISO dates → values for days that HAVE data;
    every other calendar day in the window renders as an explicit zero so
    the chart is continuous. ``no_data`` is True only when the source had
    NO rows at all in the window — an all-zero week of real rows is real
    (and honest) data, not "no data".
    """
    points = []
    total: float = 0.0
    for day in _window_dates(today, window_days):
        iso = day.isoformat()
        value = float(values_by_date.get(iso, 0) or 0)
        total += value
        if round_to is not None:
            value = round(value, round_to)
        points.append({"date": iso, "value": value})
    if round_to is not None:
        total = round(total, round_to)
    else:
        total = int(total)
    return {
        "points": points,
        "total": total,
        "no_data": not values_by_date,
        "link": dict(link),
    }


def compute_cost_projections(total_cost_usd: float, *, window_days: int, no_data: bool) -> dict[str, Any]:
    """Weekly/monthly compounding off the window's daily average.

    Honest arithmetic only: an empty window projects ``None``, never a
    fabricated zero-burn claim.
    """
    if no_data or window_days <= 0:
        return {"projected_weekly_usd": None, "projected_monthly_usd": None}
    daily_avg = total_cost_usd / window_days
    return {
        "projected_weekly_usd": round(daily_avg * 7, 6),
        "projected_monthly_usd": round(daily_avg * 30, 6),
    }


def shape_governance_activity(activity: dict[str, Any], *, persona: str) -> dict[str, Any]:
    """Persona-shape the AI-SPM activity summary.

    SAME numbers for both lenses; the executive lens drops the per-run
    sample ids (vision §1 — the board reads trends, not row ids).
    """
    runs = dict(activity.get("runs") or {})
    if persona == posture_service.PERSONA_EXECUTIVE:
        runs.pop("sample_run_ids", None)
    return {
        "window_days": activity.get("window_days"),
        "runs": runs,
        "tool_calls": activity.get("tool_calls"),
        "no_data": activity.get("no_data"),
        "link": dict(LINK_AGENTS),
    }


def compose_dashboard(
    persona: str,
    *,
    window_days: int,
    today: date,
    log_lines_by_date: dict[str, int],
    log_rows_present: bool,
    findings_created_by_date: dict[str, int],
    findings_rows_present: bool,
    rollup_runs_by_date: dict[str, int],
    rollup_cost_by_date: dict[str, float],
    rollup_rows_present: bool,
    findings: dict[str, Any],
    kpis: dict[str, Any],
    fleet: dict[str, Any],
    outlook: dict[str, Any],
    activity: dict[str, Any],
) -> dict[str, Any]:
    """Compose the collected facts into the persona-framed dashboard payload."""
    from components.shared_kernel.domain.errors import ValidationError

    persona = (persona or posture_service.PERSONA_ENGINEER).strip().lower()
    if persona not in posture_service.PERSONAS:
        raise ValidationError(f"persona must be one of {posture_service.PERSONAS}, got {persona!r}")

    log_series = compute_daily_series(log_lines_by_date, today=today, window_days=window_days, link=LINK_LOGS)
    log_series["no_data"] = not log_rows_present

    cost_series = compute_daily_series(
        rollup_cost_by_date, today=today, window_days=window_days, link=LINK_AGENTS, round_to=6
    )
    cost_series["no_data"] = not rollup_rows_present
    cost_series["total_usd"] = cost_series.pop("total")
    cost_series.update(
        compute_cost_projections(
            float(cost_series["total_usd"]), window_days=window_days, no_data=cost_series["no_data"]
        )
    )

    findings_series = compute_daily_series(
        findings_created_by_date, today=today, window_days=window_days, link=LINK_KANBAN
    )
    findings_series["no_data"] = not findings_rows_present

    runs_series = compute_daily_series(rollup_runs_by_date, today=today, window_days=window_days, link=LINK_AGENTS)
    runs_series["no_data"] = not rollup_rows_present

    posture = posture_service.compose_posture_report(persona, findings, kpis, fleet, outlook)

    kpi_bands = dict(kpis)
    kpi_bands["link"] = dict(LINK_KANBAN)

    return {
        "persona": persona,
        "window_days": window_days,
        "generated_at": datetime.now(UTC).isoformat(),
        "series": {
            "log_lines_per_day": log_series,
            "ai_cost_per_day": cost_series,
            "findings_created_per_day": findings_series,
            "runs_per_day": runs_series,
        },
        "kpi_bands": kpi_bands,
        "ctem_mapping": posture.get("ctem_mapping"),
        "posture": posture,
        "governance_activity": shape_governance_activity(activity, persona=persona),
        "links": {
            "open_findings": dict(LINK_KANBAN),
            "needs_human_backlog": dict(LINK_KANBAN),
            "kpi_bands": dict(LINK_KANBAN),
            "fleet": dict(LINK_AGENTS),
            "runs": dict(LINK_AGENTS),
            "cost": dict(LINK_AGENTS),
            "log_volume": dict(LINK_LOGS),
        },
    }


# ── ORM-backed collectors (lazy imports, per posture_service conventions) ───


def _collect_log_lines_by_date(workspace_id: str, window_days: int) -> tuple[dict[str, int], bool]:
    """Lines/day from the LogMetricBucket TOTAL_VOLUME rollups."""
    from components.integrations.application import log_metrics_query_service
    from components.integrations.application.log_metrics_service import TOTAL_VOLUME

    result = log_metrics_query_service.query_metric(
        workspace_id,
        TOTAL_VOLUME,
        window_days=window_days,
        group_by="day",
        limit=min(window_days + 1, log_metrics_query_service.MAX_ROWS),
    )
    rows = result.get("rows") or []
    return {str(row["day"]): int(row["count"] or 0) for row in rows}, bool(rows)


def _collect_findings_created_by_date(workspace_id: str, window_days: int) -> tuple[dict[str, int], bool]:
    """Findings filed per day — board cards, the posture report's own
    card excluded so the weekly report can never count itself."""
    from infrastructure.persistence.project.models import Task

    since = datetime.now(UTC) - timedelta(days=window_days)
    created_rows = (
        Task.objects.filter(
            workspace_id=workspace_id,
            source_type__startswith="ai.",
            created_at__gte=since,
        )
        .exclude(source_type=posture_service.POSTURE_REPORT_SOURCE_TYPE)
        .values_list("created_at", flat=True)
        .iterator(chunk_size=500)
    )
    by_date: dict[str, int] = {}
    present = False
    for created_at in created_rows:
        present = True
        iso = created_at.date().isoformat()
        by_date[iso] = by_date.get(iso, 0) + 1
    return by_date, present


def _collect_rollup_series(workspace_id: str, window_days: int) -> tuple[dict[str, int], dict[str, float], bool]:
    """Runs/day + cost/day from the AiActionDailyRollup read model."""
    from infrastructure.persistence.ai.agents.models import AiActionDailyRollup

    since = _utc_today() - timedelta(days=window_days - 1)
    runs_by_date: dict[str, int] = {}
    cost_by_date: dict[str, float] = {}
    present = False
    rows = AiActionDailyRollup.objects.filter(workspace_id=workspace_id, date__gte=since).only(
        "date", "runs_total", "cost_usd"
    )
    for row in rows.iterator(chunk_size=500):
        present = True
        iso = row.date.isoformat()
        runs_by_date[iso] = int(row.runs_total)
        cost_by_date[iso] = float(row.cost_usd)
    return runs_by_date, cost_by_date, present


def dashboard(
    workspace_id: str,
    persona: str = posture_service.PERSONA_ENGINEER,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Compose the chart-ready posture dashboard for one workspace."""
    workspace_id = str(workspace_id)
    window_days = max(1, min(int(window_days), MAX_WINDOW_DAYS))
    today = _utc_today()

    log_lines_by_date, log_present = _collect_log_lines_by_date(workspace_id, window_days)
    findings_by_date, findings_present = _collect_findings_created_by_date(workspace_id, window_days)
    runs_by_date, cost_by_date, rollups_present = _collect_rollup_series(workspace_id, window_days)

    return compose_dashboard(
        persona,
        window_days=window_days,
        today=today,
        log_lines_by_date=log_lines_by_date,
        log_rows_present=log_present,
        findings_created_by_date=findings_by_date,
        findings_rows_present=findings_present,
        rollup_runs_by_date=runs_by_date,
        rollup_cost_by_date=cost_by_date,
        rollup_rows_present=rollups_present,
        findings=posture_service.findings_posture(workspace_id, window_days=window_days),
        kpis=posture_service.response_kpis(workspace_id, window_days=window_days),
        fleet=posture_service.fleet_health(workspace_id, window_days=window_days),
        outlook=posture_service.forward_outlook(workspace_id),
        activity=ai_governance_service.ai_activity(workspace_id, window_days=window_days),
    )
