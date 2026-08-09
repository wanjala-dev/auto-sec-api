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
from components.agents.infrastructure.services import finding_dispatch_service as fds

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
    target specialist — ``triage_agent`` for log-watch errors today, a
    ``code_security_agent`` for SAST findings). The router groups pending
    findings by that declared target and ENQUEUES each group's dispatch
    (``dispatch_finding_specialist`` on the agent worker → the cycle's
    entitlement-gated delegator → ``AgentService.execute_agent`` — the detector
    cycle is still the autonomous orchestrator, skill §3; the router just no
    longer BLOCKS the cycle on the specialist's LLM latency).

    Why route by the finding's declared target rather than hard-code one agent:
    it SCALES. Adding a new finding→specialist path is "file findings with
    ``agent_type=<new_specialist>``" — the router picks them up with no change
    here. Routing is deterministic (each finding names its target — the
    documented ``Command(goto=…)`` pattern for known routing).

    **This detector is now the BACKSTOP, not the only trigger.** The grouping /
    lease / enqueue choreography moved to ``finding_dispatch_service`` so the
    board handler can fire the SAME dispatch the moment a routable card exists
    (a finding must never sit in an unexplained gap between "detected" and "fix
    proposed"). The cadence still sweeps every tick and stays correct on its own:
    anything the immediate path missed — a burst that outran the debounce window,
    a workspace whose gate was off at file time, a lost task — is picked up here.
    """

    slug = "ai_findings.route"
    name = "AI Finding Router"
    cadence = "frequent"
    description = "Routes pending AI findings to the specialist each finding declares (metadata.agent_type)."

    # Re-exported from the shared dispatch engine so there is exactly ONE
    # definition of what is routable / what is not a specialist. Callers and
    # tests may keep reading them off the detector.
    ROUTABLE_SOURCE_TYPES = fds.ROUTABLE_SOURCE_TYPES
    _NON_SPECIALIST = fds.NON_SPECIALIST
    _DISPATCH_LEASE_SECONDS = fds.DISPATCH_LEASE_SECONDS

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        performed_by = str((getattr(context, "extras", None) or {}).get("performed_by") or "") or None
        fds.dispatch_pending_findings(context.workspace_id, performed_by=performed_by, trigger=self.slug)
        return []


registry.register(LogWatchErrorDetector)
registry.register(LogOptimizationDetector)
registry.register(AiFindingRouterDetector)
