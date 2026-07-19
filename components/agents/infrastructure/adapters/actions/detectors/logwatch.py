"""Log-Watch detector — the deterministic sensor half of the SOC log pipeline.

Per the agents skill (§5.7, §14.9, §17): findings flow through the detector
cycle → ``persist_finding_as_task`` (the ``AIActionCreated`` path — idempotent,
audited), never a direct ``Task.objects.create``. This detector NEVER calls an
LLM (the POC hard rule — no model over the raw firehose); it scans confirmed
errors deterministically and emits an **evidence-bearing** finding per error
(signal + evidence[] + blast_radius + confidence). The ``probable_cause`` and
``recommendation`` are left empty for the triage agent (LLM-after-detection),
which the cycle routes to as a deep-pipeline worker via ``invoke_agent``.

Cross-context boundary: this agents-context detector imports only
``components.integrations.application`` (``scan_workspace_for_errors``) — never
integrations persistence — so the bounded-context rule holds.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import registry

logger = logging.getLogger(__name__)

_IMPACT_BY_SEVERITY = {"critical": 90, "high": 70, "medium": 40}


class LogWatchErrorDetector(BaseDetector):
    slug = "logwatch.error"
    name = "Log-Watch Error Detector"
    cadence = "frequent"
    description = (
        "Detects error/critical log lines in the connected AWS log stream and files evidence-bearing SOC findings."
    )
    default_config = {
        "max_objects": 20,
        "max_findings": 10,
    }

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        from components.integrations.application.log_ingest_service import scan_workspace_for_errors

        max_objects = int(self.config.get("max_objects", 20))
        max_findings = int(self.config.get("max_findings", 10))

        findings = scan_workspace_for_errors(context.workspace_id, max_objects=max_objects, only_new=True)
        results: list[DetectorResult] = []
        for finding in findings[:max_findings]:
            contract = finding.as_contract()
            title = f"[{finding.severity.upper()}] {finding.service} · {finding.message[:110]}"
            summary = (
                f"{finding.signal}\n\n{finding.message}\n\n"
                f"Confidence: {finding.confidence}. "
                f"Awaiting triage — the triage agent will propose a fix."
            )
            results.append(
                DetectorResult(
                    action_type="log_watch",
                    title=title,
                    summary=summary,
                    # ``lookup_key`` is what the cycle maps to the idempotency
                    # key — the content fingerprint dedupes repeat errors.
                    payload={**contract, "lookup_key": finding.fingerprint},
                    context={"evidence": finding.evidence, "blast_radius": finding.blast_radius},
                    detector_slug=self.slug,
                    # Attribution + the routing target the triage step delegates to.
                    agent_type="triage_agent",
                    metadata={"impact_score": _IMPACT_BY_SEVERITY.get(finding.severity, 40)},
                )
            )

        logger.info(
            "logwatch_detector workspace=%s findings=%s emitted=%s",
            context.workspace_id,
            len(findings),
            len(results),
        )
        return results


class LogOptimizationDetector(BaseDetector):
    """Temporal sensor — surfaces log *optimization* intelligence over time.

    The sibling of ``LogWatchErrorDetector``: same deterministic-first, evidence-
    bearing, AIAction-path discipline, but instead of point-in-time errors it
    aggregates recurring patterns across windows (via
    ``aggregate_workspace_log_patterns``) and files a finding when a pattern is
    both high-frequency AND sustained — an over-scheduled beat task, health-check
    noise, a service dominating volume. Findings target ``optimization_agent``
    (a distinct specialist), proving the pipeline scales to new finding KINDS
    without touching the router's logic — only its ``ROUTABLE_SOURCE_TYPES``.

    Cadence is deliberately slower than the error detector (``hourly``): the
    signal is a trend, not an incident, and a full-window re-read every cycle
    would waste S3 reads. NEVER calls an LLM (POC hard rule).
    """

    slug = "logwatch.optimization"
    name = "Log Optimization Detector"
    cadence = "hourly"
    description = (
        "Aggregates recurring log patterns over time and files optimization findings "
        "(over-scheduled jobs, health-check noise, volume hotspots)."
    )
    default_config = {
        "max_objects": 40,
        "max_findings": 10,
    }

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        from components.integrations.application.log_pattern_analyzer_service import aggregate_workspace_log_patterns

        max_objects = int(self.config.get("max_objects", 40))
        max_findings = int(self.config.get("max_findings", 10))

        findings = aggregate_workspace_log_patterns(
            context.workspace_id, max_objects=max_objects, max_findings=max_findings
        )
        results: list[DetectorResult] = []
        for finding in findings:
            contract = finding.as_contract()
            title = f"[OPTIMIZE] {finding.service} · {finding.signal[:110]}"
            summary = (
                f"{finding.signal}\n\n"
                f"Seen {finding.total_count} times total across {finding.runs_observed} runs "
                f"({finding.confidence} confidence). "
                f"Awaiting the optimization agent's concrete recommendation."
            )
            results.append(
                DetectorResult(
                    action_type="log_optimization",
                    title=title,
                    summary=summary,
                    payload={**contract, "lookup_key": finding.fingerprint},
                    context={"evidence": finding.evidence, "blast_radius": finding.blast_radius},
                    detector_slug=self.slug,
                    agent_type="optimization_agent",
                    metadata={"impact_score": min(90, finding.last_window_count)},
                )
            )

        logger.info(
            "logopt_detector workspace=%s findings=%s emitted=%s",
            context.workspace_id,
            len(findings),
            len(results),
        )
        return results


class AiFindingRouterDetector(BaseDetector):
    """Routes pending AI findings to the specialist each finding DECLARES.

    This is the consumer/routing half — the seam that expands as we add
    specialists. It emits no findings of its own. Every finding persisted via
    the AIAction path carries ``metadata.agent_type`` (the ``DetectorResult``'s
    target specialist — ``triage_agent`` for log-watch errors today; a future
    ``optimization_agent`` / ``rca_agent`` for other finding kinds). This router
    groups pending findings by that declared target and hands each group to its
    specialist through ``context.invoke_agent`` (→ ``AgentService.execute_agent``
    — the detector cycle is the autonomous orchestrator, skill §3). The
    specialist then processes its own findings with its own tools.

    Why route by the finding's declared target rather than hard-code one agent:
    it SCALES. Adding a new finding→specialist path is "file findings with
    ``agent_type=<new_specialist>``" — the router picks them up with no change
    here. Routing is deterministic today (each finding names its target — the
    documented ``Command(goto=…)`` pattern for known routing); when a finding's
    correct specialist becomes ambiguous, the target can be left unset and this
    hand-off routed through the deep planner instead (the forced-worker knob in
    ``execute_plan_once`` keeps that reliable). Detect now, route next tick (the
    cycle persists results only after every detector's ``execute`` returns).
    """

    slug = "ai_findings.route"
    name = "AI Finding Router"
    cadence = "frequent"
    description = "Routes pending AI findings to the specialist each finding declares (metadata.agent_type)."

    # Finding source_types this router owns. Grows as detectors add kinds; each
    # entry's findings route by their declared metadata.agent_type. Adding
    # ``ai.log_optimization`` here is the ENTIRE routing change needed to support
    # the new optimization specialist — the dispatch logic below is untouched.
    ROUTABLE_SOURCE_TYPES = ("ai.log_watch", "ai.log_optimization")
    # Findings targeting the orchestrator itself are not re-dispatched here.
    _NON_SPECIALIST = {"", "ai_teammate", "ai_teammate_agent", "orchestrator"}

    # A dispatch to a specialist is leased in the cache for this long so
    # overlapping 5-min cycles (beat cadence == the run's time limit) don't fire
    # a second redundant deep run for the same specialist. > one cycle, < a long
    # backlog stall. Correctness is still guaranteed by triage_finding's row
    # lock; this only saves wasted deep runs + LLM spend.
    _DISPATCH_LEASE_SECONDS = 240

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        from collections import defaultdict

        from django.core.cache import cache

        from infrastructure.persistence.project.models import Task

        if context.invoke_agent is None:
            logger.warning("ai_finding_router no invoke_agent bound; skipping workspace=%s", context.workspace_id)
            return []

        from components.agents.infrastructure.adapters.langchain.tools._finding_processing import (
            not_triaged_filter,
        )

        # Group pending findings by the specialist they declare. The handled
        # exclusion is pushed into the query (NULL-safe — see not_triaged_filter;
        # ``.exclude`` alone drops findings whose triage key isn't stamped yet)
        # so the scan stays bounded as finding history grows.
        by_specialist: dict[str, list] = defaultdict(list)
        pending = (
            Task.objects.filter(workspace_id=context.workspace_id, source_type__in=self.ROUTABLE_SOURCE_TYPES)
            .filter(not_triaged_filter())
            .only("id", "metadata")
        )
        for t in pending:
            target = ((t.metadata or {}).get("agent_type") or "").strip()
            if target in self._NON_SPECIALIST:
                continue
            by_specialist[target].append(t)

        for specialist, findings in by_specialist.items():
            # Skip if a dispatch to this specialist is already in flight (lease).
            lease_key = f"ai_finding_router:dispatch:{context.workspace_id}:{specialist}"
            if not cache.add(lease_key, "1", self._DISPATCH_LEASE_SECONDS):
                logger.info(
                    "ai_finding_router dispatch in-flight, skipping workspace=%s specialist=%s",
                    context.workspace_id,
                    specialist,
                )
                continue

            goal = (
                f"There are {len(findings)} pending findings on the SOC board assigned to you. "
                "Use your tools to list them and process each one (propose a fix, comment it, "
                "and advance the card)."
            )
            try:
                # Orchestrator-routed, deterministic named dispatch. The detector
                # cycle IS the autonomous orchestrator (§3); invoke_agent →
                # execute_agent is it calling the named sub-agent. The target is
                # KNOWN (the finding declares it), so we name it directly — the
                # planner exists to DECIDE routing for ambiguous goals, and when
                # handed a known delegation it re-routes by keyword and can
                # fabricate (§5.13). worker_agent_type pins the specialist for
                # the runner's forced-worker override so even a deep run can't
                # drift. Un-name the target (route via planner) only when the
                # correct specialist is genuinely ambiguous.
                context.invoke_agent(
                    specialist,
                    goal,
                    {
                        "worker_agent_type": specialist,
                        "source": "ai_findings.route",
                        # Verification loop (L2): the specialist self-verifies its
                        # finding output and re-runs once on a failing grade. This
                        # is the autonomous path where finding quality IS the
                        # product, so the critic's cost is worth it.
                        "max_reflections": 1,
                    },
                )
                logger.info(
                    "ai_finding_router routed workspace=%s specialist=%s pending=%s",
                    context.workspace_id,
                    specialist,
                    len(findings),
                )
            except Exception:
                logger.exception(
                    "ai_finding_router invoke_agent failed workspace=%s specialist=%s",
                    context.workspace_id,
                    specialist,
                )
        return []


registry.register(LogWatchErrorDetector)
registry.register(LogOptimizationDetector)
registry.register(AiFindingRouterDetector)
