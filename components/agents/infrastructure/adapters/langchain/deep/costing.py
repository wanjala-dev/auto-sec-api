"""Per-run LLM cost records for the deep pipeline (task #46).

The deep runner enforces ``ExecutionBudget.max_cost_usd`` against spend
accumulated in ``run_metadata["cost_usd_records"]`` — one record per priced
surface, united across concurrent ``Send`` workers by the
``merge_run_metadata`` reducer:

* ``"planner"`` — seeded by the runner from the ``DeepRunLog`` ``llm_call``
  rows that ``llm_planner._log_llm_call`` writes (tokens + ``cost_usd``
  computed from the seeded ``AIModel`` pricing).
* ``"<task_id>"`` — stamped by ``deep/adapters.build_worker_from_agent`` from
  the worker response's ``telemetry`` snapshot (the ``TelemetryCallback``
  token counters that ``BaseAgent.execute`` now ships out on the response).

Pricing honesty: when a model has no seeded pricing row (or the telemetry
spans multiple models so per-model token attribution is unknown), the record
keeps the token counts but reports ``cost_usd: None`` — the budget check
counts only spend it can substantiate, and the dashboard must not show a
false ``$0.00``. Every helper here is observation-only and never raises.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def cost_usd_for_tokens(model_name: str, input_tokens: int, output_tokens: int) -> float | None:
    """Price a token count against the seeded ``AIModel`` pricing rows.

    Mirrors ``llm_planner._log_llm_call``'s computation (per-1k input/output
    rates). Returns ``None`` when the model is unknown or unpriced so callers
    can distinguish "free" from "we don't know".
    """
    if not model_name or (input_tokens <= 0 and output_tokens <= 0):
        return None
    try:
        from decimal import Decimal

        from infrastructure.persistence.ai.llms.models import AIModel

        ai_model = AIModel.objects.filter(model_id=model_name).first()
        if ai_model is None:
            return None
        cost = (Decimal(int(input_tokens)) / Decimal(1000)) * ai_model.input_cost_per_1k + (
            Decimal(int(output_tokens)) / Decimal(1000)
        ) * ai_model.output_cost_per_1k
        return float(cost)
    except Exception:
        logger.debug("cost_usd_for_tokens failed model=%s", model_name, exc_info=True)
        return None


def worker_cost_record(response: Any) -> dict[str, Any] | None:
    """Build one ``cost_usd_records`` entry from a worker agent response.

    Reads the ``telemetry`` snapshot ``BaseAgent.execute`` attaches to its
    result payload (per-call ``TelemetryCallback`` counters). ``None`` when
    the response carries no telemetry or no token usage — nothing to record.

    The telemetry tracks aggregate tokens plus a per-model call count; cost is
    priced only when exactly ONE model served the call (otherwise per-model
    token attribution is unknown and pricing the aggregate would fabricate a
    number). Tokens are always recorded so an unpriced run still shows usage.
    """
    if not isinstance(response, dict):
        return None
    telemetry = response.get("telemetry")
    if not isinstance(telemetry, dict):
        return None
    tokens = telemetry.get("tokens") or {}
    try:
        input_tokens = int(tokens.get("input_tokens") or 0)
        output_tokens = int(tokens.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return None
    if input_tokens <= 0 and output_tokens <= 0:
        return None

    models = telemetry.get("models") or {}
    model_name = next(iter(models)) if isinstance(models, dict) and len(models) == 1 else None
    cost = cost_usd_for_tokens(model_name, input_tokens, output_tokens) if model_name else None

    return {
        "cost_usd": round(cost, 6) if isinstance(cost, float) else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": model_name,
        "llm_calls": telemetry.get("llm_calls"),
        "source": "worker_telemetry",
    }


def planner_cost_record(thread_id: str | None) -> dict[str, Any] | None:
    """Aggregate the planner's ``llm_call`` DeepRunLog rows into one record.

    ``llm_planner._log_llm_call`` persists tokens + ``cost_usd`` per planner
    invocation (it requires the ``DeepRun`` row to exist — ``_execute_deep``
    now creates it before planning so these rows actually land on the
    autonomous path). ``None`` when there is no run / no planner rows.
    """
    if not thread_id:
        return None
    try:
        from django.db.models import Sum

        from infrastructure.persistence.ai.agents.models import DeepRunLog

        aggregate = DeepRunLog.objects.filter(
            deep_run__thread_id=thread_id,
            event_type="llm_call",
            agent_type="planner",
        ).aggregate(
            cost=Sum("cost_usd"),
            input_tokens=Sum("prompt_tokens"),
            output_tokens=Sum("completion_tokens"),
        )
        cost = aggregate.get("cost")
        input_tokens = aggregate.get("input_tokens")
        output_tokens = aggregate.get("output_tokens")
        if cost is None and not input_tokens and not output_tokens:
            return None
        return {
            "cost_usd": round(float(cost), 6) if cost is not None else None,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "model": None,
            "source": "planner_llm_call_logs",
        }
    except Exception:
        logger.debug("planner_cost_record failed thread_id=%s", thread_id, exc_info=True)
        return None
