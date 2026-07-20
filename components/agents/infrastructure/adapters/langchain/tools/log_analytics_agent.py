"""Log analytics agent tools — "chat with the logs" over deterministic aggregates.

Every tool here is a thin translation layer: parse the LLM's JSON-ish input,
call the integrations application query service
(``log_metrics_query_service`` — ORM aggregates over hourly
``LogMetricBucket`` rows), and wrap the numbers in a ``ToolResult`` with a
compact human summary. The numbers in the summary are copied verbatim from
the service response — a tool NEVER computes or invents a count of its own,
and no tool here writes anything.

Counting/trend questions route to these tools, never to RAG (posture vision
§3.2: the aggregation-first rule). Cross-context boundary: imports ONLY the
integrations *application* layer, never its persistence.
"""

from __future__ import annotations

import json
import logging

from components.agents.infrastructure.adapters.langchain.base import ToolResult
from components.integrations.application import log_metrics_query_service as metrics_query
from components.integrations.application.log_metrics_service import SECURITY_METRICS

logger = logging.getLogger(__name__)

_WINDOW_ALIASES = {
    "day": 24,
    "today": 24,
    "24h": 24,
    "week": 168,
    "this week": 168,
    "7d": 168,
    "month": 720,
    "this month": 720,
    "30d": 720,
    "quarter": 2160,
    "90d": 2160,
}


def _parse_window(value) -> tuple[int, str]:
    """Coerce a window expression to ``(hours, label)``. Defaults to 7 days."""
    if value is None or str(value).strip() == "":
        return 168, "last 7 days"
    text = str(value).strip().lower()
    if text in _WINDOW_ALIASES:
        hours = _WINDOW_ALIASES[text]
        return hours, f"last {hours // 24} day(s)" if hours >= 24 else f"last {hours}h"
    if text.endswith("h") and text[:-1].isdigit():
        return max(int(text[:-1]), 1), f"last {text[:-1]}h"
    if text.endswith("d") and text[:-1].isdigit():
        days = max(int(text[:-1]), 1)
        return days * 24, f"last {days} day(s)"
    if text.isdigit():  # bare number → days
        days = max(int(text), 1)
        return days * 24, f"last {days} day(s)"
    raise ValueError(f"Unknown window {value!r}. Use e.g. '24h', '7d', '30d', 'week', 'month'.")


def _payload(input_str: str) -> dict:
    """Accept JSON, a bare metric name, or empty input."""
    text = (input_str or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    return {"metric": text}


def query_log_metric(agent, input_str: str = "") -> str | ToolResult:
    """READ — count one security metric over a window, optionally grouped."""
    try:
        payload = _payload(input_str)
        metric = payload.get("metric")
        if not metric:
            return ToolResult(
                ok=False,
                error="Missing 'metric'. " + _metrics_hint(),
            )
        hours, label = _parse_window(payload.get("window"))
        group_by = payload.get("group_by") or None
        result = metrics_query.query_metric(
            agent.workspace_id,
            metric,
            window_hours=hours,
            group_by=group_by,
        )
    except ValueError as exc:
        return ToolResult(ok=False, error=str(exc))
    except Exception:
        logger.exception("query_log_metric_failed workspace_id=%s", agent.workspace_id)
        return ToolResult(ok=False, error="Log metric query failed — see server logs.")

    if result["total"] == 0:
        message = f"No {result['metric']} data in window ({label})."
    else:
        message = f"{result['total']} {result['metric']} event(s) in the {label}."
        if group_by:
            message += f" Grouped by {group_by} ({len(result['rows'])} row(s))."
    return ToolResult(message=message, data={**result, "window": label})


def get_metric_trend(agent, input_str: str = "") -> str | ToolResult:
    """READ — classify a metric's hourly shape as spike | sustained | quiet."""
    try:
        payload = _payload(input_str)
        metric = payload.get("metric") or "total_volume"
        hours, label = _parse_window(payload.get("window"))
        result = metrics_query.classify_trend(agent.workspace_id, metric, window_hours=hours)
    except ValueError as exc:
        return ToolResult(ok=False, error=str(exc))
    except Exception:
        logger.exception("get_metric_trend_failed workspace_id=%s", agent.workspace_id)
        return ToolResult(ok=False, error="Trend classification failed — see server logs.")

    if result["total"] == 0:
        message = f"No {result['metric']} data in window ({label}) — pattern: quiet."
    else:
        message = (
            f"{result['metric']} over the {label}: pattern={result['pattern']} "
            f"(total={result['total']}, peak hour={result['max_hour_count']}, "
            f"median hourly={result['median_hourly']}, "
            f"active {result['active_hours']}/{result['window_hours']}h)."
        )
    return ToolResult(message=message, data={**result, "window": label})


def get_top_sources(agent, input_str: str = "") -> str | ToolResult:
    """READ — top attack sources (derived IPs) for a metric over a window."""
    try:
        payload = _payload(input_str)
        metric = payload.get("metric")
        if not metric:
            return ToolResult(ok=False, error="Missing 'metric'. " + _metrics_hint())
        hours, label = _parse_window(payload.get("window"))
        limit = int(payload.get("limit") or 10)
        result = metrics_query.top_sources(agent.workspace_id, metric, window_hours=hours, limit=limit)
    except ValueError as exc:
        return ToolResult(ok=False, error=str(exc))
    except Exception:
        logger.exception("get_top_sources_failed workspace_id=%s", agent.workspace_id)
        return ToolResult(ok=False, error="Top-sources query failed — see server logs.")

    if not result["sources"]:
        message = f"No {result['metric']} events with a derivable source IP in the {label}."
    else:
        top = ", ".join(f"{row['source']} ({row['count']})" for row in result["sources"][:5])
        message = f"Top {result['metric']} sources in the {label}: {top}."
    return ToolResult(message=message, data={**result, "window": label})


def list_available_metrics(agent, input_str: str = "") -> str | ToolResult:
    """READ — the security-metric taxonomy with descriptions."""
    return ToolResult(
        message="Available log security metrics (hourly aggregates):",
        data={"metrics": SECURITY_METRICS},
    )


def _metrics_hint() -> str:
    return "Valid metrics: " + ", ".join(sorted(SECURITY_METRICS)) + "."
