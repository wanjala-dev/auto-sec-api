"""Detector automation cycle (extracted from legacy OrchestratorAgent).

The detector loop used to live as `OrchestratorAgent.run_detector_cycle`
inside a 600-line ReAct agent class. As part of retiring the legacy
agent (in favour of the LangGraph-native deep pipeline), the detector
logic now lives here as a plain function so the Celery cron task can
call it directly without instantiating any agent.

What it does (Phase 5 of Agents-as-Teammates migration — no more
``AIAction`` rows):

1. Resolves the workspace + AI teammate identity (creates if missing).
2. Builds a `DetectorContext` with `invoke_agent` bound to a delegator
   that respects the workspace's per-agent entitlements.
3. Runs every registered detector with timeout + parallelism budgets.
4. Persists each detector result as a Kanban Task via
   ``persist_finding_as_task`` — narrative on ``Task.description``,
   detector context on ``Task.metadata``.
5. Optionally asks an LLM to summarise the resulting signals and
   propose extra actions; persists those as Tasks too.

It does NOT use a ReAct executor or sub-agent tools. The detector
delegator hits `AgentService.execute_agent` directly, which routes
through the deep pipeline when the target agent has `mode == "deep"`
configured.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from components.shared_kernel.domain.errors import NotFoundError


def _utc_now():
    """Stdlib replacement for ``django.utils.timezone.now`` (UTC, tz-aware)."""
    return datetime.now(UTC)


def _ensure_aware(value):
    """Stdlib replacement for ``django.utils.timezone.make_aware``."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _is_aware(value):
    """Stdlib replacement for ``django.utils.timezone.is_aware``."""
    return value.tzinfo is not None


logger = logging.getLogger(__name__)


def _get_detector_modules():
    from components.agents.domain.detectors import base as detector_base

    # Import the concrete detector modules so their module-level
    # ``registry.register(...)`` calls run and populate the registry. Detectors
    # register at import time; without an import site the registry stays empty
    # (which it was in the fork). The security-relevant LogWatch detector is
    # wired here; add other detector modules to this list to activate them.
    from components.agents.infrastructure.adapters.actions.detectors import (  # noqa: F401
        logwatch,
        run_quality,
    )
    from components.agents.infrastructure.adapters.actions.detectors import (
        registry as detector_registry,
    )

    return detector_base, detector_registry


def _get_workspace_model():
    try:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace
    except ImportError:
        return None


def _build_detectors(detector_entries: list[Any] | None) -> list:
    _, det_registry = _get_detector_modules()
    detectors: list = []
    if detector_entries:
        for entry in detector_entries:
            slug = entry.get("slug") if isinstance(entry, dict) else entry
            if not slug:
                continue
            config = entry.get("config") if isinstance(entry, dict) else {}
            try:
                detectors.append(det_registry.create(slug, config=config))
            except Exception as exc:
                logger.exception("Failed to register detector %s: %s", slug, exc)
    else:
        for detector_cls in det_registry.all_detectors():
            try:
                detectors.append(detector_cls())
            except Exception as exc:
                logger.exception("Failed to instantiate detector %s: %s", detector_cls, exc)
    return detectors


def _delegate_to_agent(
    *,
    agent_type: str,
    query: str,
    context: dict[str, Any],
    performer_id: str,
    workspace,
) -> dict[str, Any]:
    """Detector → domain agent delegator.

    Replaces `OrchestratorAgent._invoke_domain_agent`. Honours the same
    `resolve_agent_entitlement` policy gate so detectors can't bypass
    workspace permissions.
    """
    from components.agents.application.policies.agent_entitlements import (
        resolve_agent_entitlement,
    )
    from components.agents.infrastructure.services.agents_service import (
        get_agent_service,
    )

    agent_service = get_agent_service()
    allowed, reason, canonical_slug = resolve_agent_entitlement(str(workspace.id), agent_type)
    if not allowed:
        logger.warning(
            "[detector_cycle] denied delegation workspace=%s agent=%s reason=%s",
            workspace.id,
            agent_type,
            reason,
        )
        return {
            "success": False,
            "code": "agent_not_entitled",
            "reason": reason,
            "agent_type": canonical_slug or agent_type,
        }

    department_id = (context or {}).get("department_id")
    agent_info = agent_service.get_or_create_agent(
        agent_type=agent_type,
        user_id=performer_id,
        workspace_id=str(workspace.id),
        department_id=department_id,
    )
    try:
        return (
            agent_service.execute_agent(
                agent_info["agent_id"],
                query,
                performed_by=performer_id,
                context=context or {},
            )
            or {}
        )
    except PermissionError as exc:
        return {"success": False, "error": str(exc), "agent_type": agent_type}


def _resolve_idempotency_key(payload: dict[str, Any] | None) -> str:
    """Derive the helper's idempotency key from the detector's payload.

    Detectors historically stuffed their dedup field on
    ``payload.lookup_key``; that's what we map to first. Fall back to a
    UUID when the detector didn't set one — better to over-persist than
    raise on a missing field.
    """
    if isinstance(payload, dict):
        lookup_key = payload.get("lookup_key")
        if lookup_key:
            return f"lookup_key:{lookup_key}"
    return f"detector_cycle_uuid:{uuid.uuid4()}"


def run_detector_cycle(
    workspace_id: str,
    *,
    detector_entries: list[Any] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the detector automation cycle for one workspace.

    Args:
        workspace_id: workspace UUID.
        detector_entries: optional list of detector slugs (or
            ``{"slug": ..., "config": ...}`` dicts) to limit the run.
            Defaults to every detector in the registry.
        extras: optional context dict passed to detectors.

    Returns:
        Summary dict with detector outcomes, signals, created task ids
        and any LLM-suggested follow-ups.
    """
    Workspace = _get_workspace_model()
    if Workspace is None:
        raise RuntimeError("Workspace model unavailable")

    queryset = getattr(Workspace, "_base_manager", None) or Workspace.objects
    try:
        workspace = queryset.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise NotFoundError(f"Workspace {workspace_id} not found")

    # SEE-202 — emergency kill switch. When tripped, the autonomous detector
    # skips the whole cycle (no LLM calls, no findings) so a misbehaving AI can
    # be stopped platform-wide without waiting for a deploy.
    from components.agents.application.policies.ai_kill_switch import is_ai_killed

    if is_ai_killed(workspace_id):
        logger.info(
            "detector_cycle skipped: ai_kill_switch engaged workspace_id=%s",
            workspace_id,
        )
        return {"workspace_id": str(workspace_id), "halted": True, "reason": "ai_kill_switch"}

    from components.agents.application.facades.agent_permissions_facade import (
        ensure_agents_team,
        ensure_ai_identity,
    )
    from components.agents.application.facades.ai_teammate_facade import (
        ensure_agents_board,
    )
    from components.agents.application.handlers.specialist_persistence_service import (
        persist_finding_as_task,
    )
    from components.agents.infrastructure.services.agents_board_service import (
        SUGGESTED,
    )

    teammate_profile, ai_user = ensure_ai_identity(workspace)
    try:
        ensure_agents_team(workspace, ai_user)
    except Exception:  # pragma: no cover - best effort
        logger.warning(
            "Unable to ensure Agents team for workspace=%s",
            workspace_id,
            exc_info=True,
        )
    teammate = teammate_profile

    board = ensure_agents_board(workspace)
    suggested_column = board.column(SUGGESTED)
    ai_user_id = str(board.team.created_by_id)

    detectors = _build_detectors(detector_entries)

    det_base, _ = _get_detector_modules()
    detector_context = det_base.DetectorContext(
        workspace_id=str(workspace.id),
        teammate_id=str(teammate.id),
        run_at=_utc_now(),
        last_run_at=teammate.last_run_at,
        config=teammate.config or {},
        extras=extras or {},
        invoke_agent=lambda agent_type, agent_query, agent_context=None: _delegate_to_agent(
            agent_type=agent_type,
            query=agent_query,
            context=agent_context or {},
            performer_id=str(teammate.user_id),
            workspace=workspace,
        ),
    )

    from components.agents.application.services.detector_runner import run_all_detectors

    start_time = time.time()
    cfg = teammate.config or {}
    detector_timeout = cfg.get("detector_timeout_seconds", 30)
    detector_parallelism = int(cfg.get("detector_parallelism", 4))
    detector_outcomes = run_all_detectors(
        detectors,
        detector_context,
        timeout_per_detector=float(detector_timeout),
        max_parallel=max(1, detector_parallelism),
    )

    created_task_ids: list[str] = []
    detector_summaries: list[dict[str, Any]] = []
    all_signals: list[dict[str, Any]] = []

    for outcome in detector_outcomes:
        if outcome.skipped or outcome.error:
            detector_summaries.append(
                {
                    "detector": outcome.slug,
                    "skipped": True,
                    "reason": outcome.skip_reason or outcome.error,
                    "error": outcome.error,
                    "duration_ms": outcome.duration_ms,
                }
            )
            continue

        all_signals.extend(outcome.signals)
        detector_summary = {
            "detector": outcome.slug,
            "results": len(outcome.results),
            "created_actions": 0,
            "duration_ms": outcome.duration_ms,
        }

        for result in outcome.results:
            try:
                task_id = persist_finding_as_task(
                    workspace=workspace,
                    suggested_column=suggested_column,
                    ai_user_id=ai_user_id,
                    title=result.title,
                    summary=result.summary,
                    source_type=f"ai.{result.action_type}",
                    agent_type=result.agent_type or "ai_teammate",
                    detector_key=result.detector_slug or outcome.slug,
                    payload_data=result.payload,
                    context=result.context,
                    impact_score=int(result.metadata.get("impact_score", 0)) if result.metadata else 0,
                    idempotency_key=_resolve_idempotency_key(result.payload),
                )
            except Exception:
                logger.exception(
                    "detector_cycle_persist_failed detector=%s action_type=%s",
                    outcome.slug,
                    result.action_type,
                )
                continue

            if task_id is None:
                # Idempotent replay — already have a task for this finding.
                continue
            created_task_ids.append(str(task_id))
            detector_summary["created_actions"] += 1

        detector_summaries.append(detector_summary)

    # Stamp the teammate so the next cron run can window from the last
    # successful invocation. Kept inline (was previously a
    # ``AIActionService.update_last_run`` call) so this module no
    # longer depends on the actions service.
    teammate.last_run_at = _utc_now()
    teammate.save(update_fields=["last_run_at", "updated_at"])

    # ── Optional LLM summary of signals ──
    agent_summary: str | None = None
    llm_actions_data: list[dict[str, Any]] = []
    if all_signals:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            from components.knowledge.infrastructure.factories.llms.factory import (
                LLMFactory,
            )

            signals_json = json.dumps(all_signals, ensure_ascii=False)
            if len(signals_json) <= 8000:
                llm = LLMFactory.get_llm()
                response = llm.invoke(
                    [
                        SystemMessage(
                            content=(
                                "You are reviewing automation signals from detectors. "
                                'Return STRICT JSON of the form {"actions": [...]} '
                                "where each action has action_type/title/summary/payload/context."
                            )
                        ),
                        HumanMessage(content=signals_json),
                    ]
                )
                agent_summary = (getattr(response, "content", None) or str(response)).strip()
                try:
                    parsed = json.loads(agent_summary)
                    if isinstance(parsed, dict):
                        parsed = parsed.get("actions") or parsed.get("data") or []
                    if isinstance(parsed, list):
                        llm_actions_data = parsed
                except json.JSONDecodeError:
                    logger.warning("LLM signal-summary not valid JSON; ignoring auto actions")
        except Exception as exc:  # pragma: no cover - LLM is optional
            logger.warning("LLM signal summary skipped: %s", exc)

    llm_created = 0
    if llm_actions_data and not created_task_ids:
        from components.agents.infrastructure.services.agent_permissions_service import (
            resolve_ai_teammate_alias,
        )

        alias = resolve_ai_teammate_alias(workspace)
        for item in llm_actions_data:
            try:
                action_type = item.get("action_type") or "teammate.note"
                payload = item.get("payload") or {}
                task_id = persist_finding_as_task(
                    workspace=workspace,
                    suggested_column=suggested_column,
                    ai_user_id=ai_user_id,
                    title=item.get("title") or f"{alias} update",
                    summary=item.get("summary") or "",
                    source_type=f"ai.{action_type}",
                    agent_type=item.get("agent_type") or "ai_teammate",
                    detector_key=item.get("detector") or "teammate.llm",
                    payload_data=payload,
                    context=item.get("context") or {},
                    impact_score=int(item.get("impact_score", 0)),
                    idempotency_key=_resolve_idempotency_key(payload),
                )
            except Exception:
                logger.exception(
                    "detector_cycle_llm_persist_failed action_type=%s",
                    item.get("action_type"),
                )
                continue
            if task_id is None:
                continue
            created_task_ids.append(str(task_id))
            llm_created += 1

    execution_time_ms = int((time.time() - start_time) * 1000)
    summary_text = f"Ran {len(detectors)} detectors, created {len(created_task_ids)} actions"
    if llm_created:
        summary_text += f" (LLM generated {llm_created} actions)"

    return {
        "success": True,
        "result": summary_text,
        "actions_created": len(created_task_ids),
        "actions": created_task_ids,
        "execution_time_ms": execution_time_ms,
        "detectors": detector_summaries,
        "signals": all_signals,
        "agent_summary": agent_summary,
        "llm_actions": llm_actions_data,
    }
