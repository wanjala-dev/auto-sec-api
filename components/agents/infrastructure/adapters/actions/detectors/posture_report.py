"""Weekly posture-report detector — the scheduled posture heartbeat.

Vision §7 open decision, answered "yes": the posture aggregates also run as a
weekly detector that files ONE evidence-bearing report finding on the board
(``docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md``). Same discipline as
``AgentRunQualityDetector``:

* **NO LLM** — the report body IS the deterministic engineer-persona
  aggregates from ``posture_service`` (pure ORM + arithmetic). The posture
  agent narrates on demand; this card just persists the week's numbers.
* **Evidence-bearing** — the payload carries the full aggregate structure
  (counts, medians, bands, sample task ids), so a human can audit every
  claim without re-running anything.
* **Not auto-routed** — a posture report is operator reading material, not a
  fix task. The ``DetectorResult`` declares NO specialist ``agent_type`` and
  ``ai.posture_report`` is not in the router's ``ROUTABLE_SOURCE_TYPES``.
  ``posture_service`` also excludes this source_type from every aggregate so
  the report can never count itself.
* **Weekly cadence, twice-guarded** — a cache lease keeps the cheap re-runs
  down (the detector cycle beats far more often than weekly), and the
  ``lookup_key`` fingerprint buckets by ISO week, so ``persist_finding_as_task``
  files at most ONE report card per workspace per week regardless of how many
  cycles run. Correctness never depends on the lease.
* **No zero-activity noise** — a workspace with no findings and no runs in
  the window gets no weekly card (an empty report every week is noise, not
  signal); the posture agent still answers interactively with honest
  no_data flags.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import registry

logger = logging.getLogger(__name__)

SOURCE_TYPE = "ai.posture_report"


class PostureReportDetector(BaseDetector):
    slug = "posture_report"
    name = "Weekly Posture Report Detector"
    cadence = "weekly"
    description = (
        "Composes the deterministic posture aggregates (findings posture, response KPIs vs industry "
        "bands, fleet health, forward outlook) into one evidence-bearing weekly report finding. "
        "Never calls an LLM; deduped to one card per workspace per ISO week."
    )
    default_config = {
        "window_days": 7,
    }

    # The detector cycle runs on a frequent beat; this report only needs a
    # weekly card. The cache lease self-gates re-computation to once a day —
    # cheap insurance, while the ISO-week lookup_key fingerprint is what
    # actually guarantees at-most-one card per week (same pattern as
    # AgentRunQualityDetector's lease + day fingerprint).
    _CADENCE_LEASE_SECONDS = 24 * 3600

    def should_run(self, context: DetectorContext) -> bool:
        try:
            from django.core.cache import cache

            return bool(
                cache.add(f"posture_report_detector:lease:{context.workspace_id}", "1", self._CADENCE_LEASE_SECONDS)
            )
        except Exception:
            return True

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        from components.agents.application.services import posture_service

        cfg = {**self.default_config, **(self.config or {})}
        window_days = int(cfg.get("window_days", 7))

        findings = posture_service.findings_posture(context.workspace_id, window_days=window_days)
        kpis = posture_service.response_kpis(context.workspace_id, window_days=window_days)
        fleet = posture_service.fleet_health(context.workspace_id, window_days=window_days)
        outlook = posture_service.forward_outlook(context.workspace_id)

        activity = findings["open_findings"]["total"] + findings["toil"]["handled_total"] + fleet["deep_runs"]["total"]
        if activity == 0:
            logger.info(
                "posture_report_detector skipped: zero activity workspace=%s window_days=%d",
                context.workspace_id,
                window_days,
            )
            return []

        # The board card carries the ENGINEER-persona composition — full
        # drill-down with sample ids; the operator reading a board card is the
        # engineer lens by definition. The exec lens stays an on-demand tool.
        report = posture_service.compose_posture_report(
            posture_service.PERSONA_ENGINEER, findings, kpis, fleet, outlook
        )

        iso = context.run_at.isocalendar()
        week_bucket = f"{iso[0]}-W{iso[1]:02d}"
        fingerprint = f"posture_report:{week_bucket}"

        open_total = findings["open_findings"]["total"]
        backlog = findings["needs_human_backlog"]["count"]
        handled = findings["toil"]["handled_total"]
        open_high = findings["open_findings"]["by_severity"].get("high", 0) + findings["open_findings"][
            "by_severity"
        ].get("critical", 0)
        # Deterministic impact: a report with an escalation backlog or open
        # high/critical findings deserves more attention than a quiet week.
        impact = 60 if (backlog > 0 or open_high > 0) else 40

        title = f"Weekly security posture report — {week_bucket}"
        summary = (
            f"Deterministic posture aggregates for the last {window_days} days: {open_total} finding(s) open, "
            f"{handled} handled ({findings['toil']['auto_triaged']} auto-triaged, "
            f"{findings['toil']['escalated_to_human']} escalated), needs-human backlog {backlog}. "
            "Response KPIs are medians against industry bands; fleet health covers run success, rubric "
            "verdicts, cost and human votes; the outlook is honest week-over-week deltas. "
            "CTEM frame: detectors = Discovery, severity/impact = Prioritization, grounded verification + "
            "rubric grading = Validation, triage/board/draft-PRs = Mobilization. "
            "Every number's evidence is in this card's payload — no model produced any of it."
        )

        result = DetectorResult(
            action_type="posture_report",
            title=title,
            summary=summary,
            payload={
                "lookup_key": fingerprint,
                "signal": title,
                "confidence": "high",  # deterministic aggregation, not an estimate
                "week": week_bucket,
                "window_days": window_days,
                "report": report,
                "evidence": [
                    {
                        "type": "aggregate",
                        "detail": (
                            f"open={open_total} handled={handled} needs_human_backlog={backlog} "
                            f"deep_runs={fleet['deep_runs']['total']} window={window_days}d"
                        ),
                    },
                    {
                        "type": "sample_findings",
                        "detail": ", ".join(findings["open_findings"]["sample_task_ids"]) or "(none open)",
                    },
                ],
                "computed_at": context.run_at.isoformat(),
            },
            context={
                "evidence": [
                    {
                        "open_findings": open_total,
                        "handled_in_window": handled,
                        "needs_human_backlog": backlog,
                        "deep_runs_in_window": fleet["deep_runs"]["total"],
                        "window_days": window_days,
                    }
                ],
                "blast_radius": {
                    "window_days": window_days,
                    "open_findings": open_total,
                },
            },
            detector_slug=self.slug,
            # Deliberately NO specialist target — the report is operator
            # reading material; the router never dispatches this source_type.
            agent_type=None,
            metadata={"impact_score": impact},
        )

        logger.info(
            "posture_report_detector workspace=%s week=%s open=%d handled=%d backlog=%d",
            context.workspace_id,
            week_bucket,
            open_total,
            handled,
            backlog,
        )
        return [result]


registry.register(PostureReportDetector)
