"""Agent-run quality detector — the online evaluator over production traces.

The L4 feeder (task #46): reads the ``run_telemetry`` that
``dispatch_finding_specialist`` stamps onto handled findings (task #58) plus
the triage outcomes the specialists themselves stamp, aggregates per
``agent_type`` over a rolling window, and files an evidence-bearing finding on
the board when a quality threshold SUSTAINS — needs-human rate, rubric
first-pass failure rate, worker retry rate, budget trips.

Hard rules, same as every sensor in this registry:

* **NO LLM** (the POC hard rule) — the aggregation is pure ORM + arithmetic.
  Quality judgment already happened upstream (grounded verifier, rubric
  grader, critic); this detector only counts the outcomes.
* **Evidence-bearing** — the finding's payload IS the aggregated numbers
  (numerator/denominator/threshold/window + sample finding ids), so a human
  can audit the claim without re-running anything.
* **Not auto-routed** — a sustained quality regression in an agent is an
  operator decision (retune the rubric? adjust the advisor prompt? pull the
  agent?), so the ``DetectorResult`` deliberately declares NO specialist
  ``agent_type``. The router only owns its ``ROUTABLE_SOURCE_TYPES`` anyway;
  this finding's ``ai.agent_run_quality`` is not among them.
* **Sustained, not blips** — a metric only trips when its own denominator has
  at least ``min_findings`` observations in the window. Three bad findings in
  a row is a blip; five-plus at a >50% failure rate is a signal.

Idempotency: the ``lookup_key`` fingerprint buckets by (agent, metric, day),
so a persisting breach files at most one finding per agent/metric/day and a
recurrence next week files a fresh one.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import registry

logger = logging.getLogger(__name__)

SOURCE_TYPE = "ai.agent_run_quality"

# Metric slugs — stable identifiers used in fingerprints + payloads.
METRIC_NEEDS_HUMAN = "needs_human_rate"
METRIC_RUBRIC_FIRST_PASS_FAIL = "rubric_first_pass_fail_rate"
METRIC_RETRY = "retry_rate"
METRIC_BUDGET_TRIPS = "budget_trips"

# Rubric verdicts that mean the answer did NOT pass on the first attempt.
_RUBRIC_FAIL_VERDICTS = frozenset({"failed", "max_iterations_reached"})


def _rubric_first_pass_failed(verdict: Any) -> bool | None:
    """Did this finding's graded answer fail its first rubric pass?

    ``None`` = no rubric verdict on the finding (not graded — excluded from
    the metric's denominator). A verdict with ``iterations >= 2`` means the
    grader demanded at least one revision (first pass failed even if the
    re-run eventually satisfied); a terminal fail verdict counts regardless.
    """
    if not isinstance(verdict, dict):
        return None
    try:
        iterations = int(verdict.get("iterations") or 0)
    except (TypeError, ValueError):
        iterations = 0
    result = str(verdict.get("verdict") or "")
    return iterations >= 2 or result in _RUBRIC_FAIL_VERDICTS


def aggregate_run_quality(observations: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic per-agent quality aggregation. Pure — no ORM, no LLM.

    Args:
        observations: one dict per handled finding:
            ``{"id": str, "agent": str, "needs_human": bool,
               "rubric": dict | None, "retries": int | None,
               "budget_exceeded": str | None, "has_telemetry": bool}``
            ``retries``/``budget_exceeded`` are only meaningful when
            ``has_telemetry`` — findings handled before the telemetry stamp
            shipped are excluded from telemetry-based denominators instead of
            being counted as clean.
        config: thresholds (see ``AgentRunQualityDetector.default_config``).

    Returns:
        One breach dict per (agent, metric) whose threshold sustained:
        ``{"agent_type", "metric", "value", "threshold", "numerator",
           "denominator", "sample_task_ids"}``.
    """
    min_findings = int(config.get("min_findings", 5))
    needs_human_threshold = float(config.get("needs_human_rate_threshold", 0.5))
    rubric_threshold = float(config.get("rubric_first_pass_fail_rate_threshold", 0.5))
    retry_threshold = float(config.get("retry_rate_threshold", 0.5))
    budget_trip_min = int(config.get("budget_trip_min", 2))
    max_samples = int(config.get("max_sample_task_ids", 10))

    by_agent: dict[str, list[dict[str, Any]]] = {}
    for obs in observations:
        agent = str(obs.get("agent") or "").strip()
        if agent:
            by_agent.setdefault(agent, []).append(obs)

    breaches: list[dict[str, Any]] = []
    for agent, rows in sorted(by_agent.items()):

        def _breach(
            metric: str,
            offenders: list[dict],
            denominator: int,
            value: float,
            threshold: float,
            _agent: str = agent,  # bound per-iteration so the closure can't drift (B023)
        ) -> dict:
            return {
                "agent_type": _agent,
                "metric": metric,
                "value": round(value, 4),
                "threshold": threshold,
                "numerator": len(offenders),
                "denominator": denominator,
                "sample_task_ids": [str(o.get("id")) for o in offenders[:max_samples]],
            }

        # needs_human rate — over every handled finding (the triage stamp is
        # always present on handled rows, telemetry or not).
        offenders = [o for o in rows if o.get("needs_human")]
        if len(rows) >= min_findings:
            rate = len(offenders) / len(rows)
            if rate > needs_human_threshold:
                breaches.append(_breach(METRIC_NEEDS_HUMAN, offenders, len(rows), rate, needs_human_threshold))

        # rubric first-pass failure rate — over rubric-graded findings only.
        graded = [(o, _rubric_first_pass_failed(o.get("rubric"))) for o in rows]
        graded = [(o, failed) for o, failed in graded if failed is not None]
        offenders = [o for o, failed in graded if failed]
        if len(graded) >= min_findings:
            rate = len(offenders) / len(graded)
            if rate > rubric_threshold:
                breaches.append(_breach(METRIC_RUBRIC_FIRST_PASS_FAIL, offenders, len(graded), rate, rubric_threshold))

        # retry rate — over telemetry-bearing findings only.
        telemetered = [o for o in rows if o.get("has_telemetry")]
        offenders = [o for o in telemetered if (o.get("retries") or 0) > 0]
        if len(telemetered) >= min_findings:
            rate = len(offenders) / len(telemetered)
            if rate > retry_threshold:
                breaches.append(_breach(METRIC_RETRY, offenders, len(telemetered), rate, retry_threshold))

        # budget trips — an absolute count, not a rate: even two runs that hit
        # a safety cap in one window is operator-worthy.
        offenders = [o for o in telemetered if o.get("budget_exceeded")]
        if offenders and len(offenders) >= budget_trip_min:
            breaches.append(
                _breach(
                    METRIC_BUDGET_TRIPS,
                    offenders,
                    len(telemetered),
                    float(len(offenders)),
                    float(budget_trip_min),
                )
            )

    return breaches


class AgentRunQualityDetector(BaseDetector):
    slug = "ai_findings.run_quality"
    name = "Agent Run Quality Detector"
    cadence = "hourly"
    description = (
        "Aggregates specialists' triage outcomes + run telemetry over a rolling window and files an "
        "evidence-bearing finding when a quality threshold sustains (needs-human rate, rubric first-pass "
        "failures, retries, budget trips). Deterministic — never calls an LLM."
    )
    default_config = {
        "window_hours": 24,
        "min_findings": 5,
        "needs_human_rate_threshold": 0.5,
        "rubric_first_pass_fail_rate_threshold": 0.5,
        "retry_rate_threshold": 0.5,
        "budget_trip_min": 2,
        "max_sample_task_ids": 10,
    }

    # The cycle runs on a frequent beat; this aggregation only needs to run
    # hourly. A cache lease self-gates the cadence (same pattern as the
    # router's dispatch lease) — correctness never depends on it, since the
    # daily fingerprint dedupes the finding anyway.
    _CADENCE_LEASE_SECONDS = 3600

    def should_run(self, context: DetectorContext) -> bool:
        try:
            from django.core.cache import cache

            return bool(
                cache.add(f"run_quality_detector:lease:{context.workspace_id}", "1", self._CADENCE_LEASE_SECONDS)
            )
        except Exception:
            return True

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        from infrastructure.persistence.project.models import Task

        cfg = {**self.default_config, **(self.config or {})}
        window_hours = int(cfg.get("window_hours", 24))
        window_start = context.run_at - timedelta(hours=window_hours)

        handled = (
            Task.objects.filter(
                workspace_id=context.workspace_id,
                source_type__startswith="ai.",
                metadata__triage__status="triaged",
                updated_at__gte=window_start,
            )
            .exclude(source_type=SOURCE_TYPE)
            .only("id", "metadata")
        )

        observations: list[dict[str, Any]] = []
        for task in handled:
            meta = task.metadata or {}
            triage = meta.get("triage") or {}
            telemetry = meta.get("run_telemetry")
            has_telemetry = isinstance(telemetry, dict)
            telemetry = telemetry if has_telemetry else {}
            observations.append(
                {
                    "id": str(task.id),
                    "agent": str(triage.get("agent") or ""),
                    "needs_human": bool(triage.get("needs_human")),
                    "rubric": telemetry.get("rubric_verdicts"),
                    "retries": telemetry.get("worker_retries"),
                    "budget_exceeded": telemetry.get("budget_exceeded"),
                    "has_telemetry": has_telemetry,
                }
            )

        breaches = aggregate_run_quality(observations, cfg)
        day_bucket = context.run_at.date().isoformat()

        results: list[DetectorResult] = []
        for breach in breaches:
            agent_type = breach["agent_type"]
            metric = breach["metric"]
            if metric == METRIC_BUDGET_TRIPS:
                value_text = f"{breach['numerator']} run(s) hit a budget cap"
                impact = 70
            else:
                value_text = f"{breach['value'] * 100:.0f}% ({breach['numerator']}/{breach['denominator']})"
                impact = int(min(90, breach["value"] * 100))
            title = f"[RUN QUALITY] {agent_type} · {metric} {value_text} over last {window_hours}h"
            summary = (
                f"Online evaluation over production runs: `{agent_type}` sustained "
                f"{metric.replace('_', ' ')} of {value_text} across {breach['denominator']} handled "
                f"finding(s) in the last {window_hours}h (threshold: {breach['threshold']}). "
                "The evidence below is the deterministic aggregate — no model judged this. "
                "Review the sampled findings and decide the intervention (retune rubric/advisor, "
                "adjust budgets, or pull the agent); this finding is deliberately NOT routed to a fix agent."
            )
            fingerprint = f"agent_run_quality:{agent_type}:{metric}:{day_bucket}"
            results.append(
                DetectorResult(
                    action_type="agent_run_quality",
                    title=title,
                    summary=summary,
                    payload={
                        "lookup_key": fingerprint,
                        "signal": title,
                        "confidence": "high",  # deterministic count, not an estimate
                        "agent_under_review": agent_type,
                        "metric": metric,
                        "value": breach["value"],
                        "threshold": breach["threshold"],
                        "numerator": breach["numerator"],
                        "denominator": breach["denominator"],
                        "window_hours": window_hours,
                        "sample_task_ids": breach["sample_task_ids"],
                        "evidence": [
                            {
                                "type": "aggregate",
                                "detail": (
                                    f"{metric}={breach['value']} over {breach['denominator']} findings "
                                    f"(threshold {breach['threshold']}, window {window_hours}h)"
                                ),
                            },
                            {
                                "type": "sample_findings",
                                "detail": ", ".join(breach["sample_task_ids"]) or "(none)",
                            },
                        ],
                        "computed_at": context.run_at.isoformat(),
                    },
                    context={
                        "evidence": [
                            {
                                "metric": metric,
                                "numerator": breach["numerator"],
                                "denominator": breach["denominator"],
                                "value": breach["value"],
                                "threshold": breach["threshold"],
                            }
                        ],
                        "blast_radius": {
                            "agent_type": agent_type,
                            "findings_in_window": breach["denominator"],
                            "window_hours": window_hours,
                        },
                    },
                    detector_slug=self.slug,
                    # Deliberately NO specialist target — a human owns the
                    # intervention. persist_finding_as_task attributes the
                    # card to the teammate; the router never touches this
                    # source_type.
                    agent_type=None,
                    metadata={"impact_score": impact},
                )
            )

        logger.info(
            "run_quality_detector workspace=%s handled=%d breaches=%d emitted=%d",
            context.workspace_id,
            len(observations),
            len(breaches),
            len(results),
        )
        return results


registry.register(AgentRunQualityDetector)
