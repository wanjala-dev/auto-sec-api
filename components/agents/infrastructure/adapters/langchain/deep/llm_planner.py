"""
LLM-backed planner stub that returns a PlanSpec from a goal prompt.

This is intentionally lightweight and JSON-only to keep hallucinations contained.
It uses LLMFactory to build a chat model and expects the model to return a JSON
object with a top-level `tasks` array.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# LangChain 1.x: langchain.schema shim removed — import from langchain_core.
from langchain_core.messages import HumanMessage, SystemMessage

from components.agents.domain.services.deep.planners import build_plan_from_actions
from components.agents.domain.value_objects.plan_schemas import BudgetLine, PlanSpec
from components.agents.domain.value_objects.plan_schemas import Priority, TaskSpec, TaskStatus

logger = logging.getLogger(__name__)


# ── Prompts (Wave 3) ─────────────────────────────────────────────
# Prompts moved to file-backed PromptRegistry; the constants below
# are resolved at import time from
# ``components/agents/infrastructure/prompts/data/*.yaml`` so a v2
# can be A/B-tested against v1 by flipping the ``active`` pointer in
# the YAML without code changes. The SYSTEM_PROMPT_TEMPLATE name is
# retained for the test suite that still monkeypatches it.
from components.agents.infrastructure.prompts.registry import PromptRegistry as _PromptRegistry

SYSTEM_PROMPT_TEMPLATE = _PromptRegistry.get("planner.system")


def _build_agent_catalog() -> str:
    """Return a markdown bullet list of every registered agent with its
    summary, so the planner LLM can pick the right specialist per task.

    Reads the live ``AgentRegistry`` so adding a new agent module
    automatically updates the catalog the planner sees — no
    duplicated lists to keep in sync.
    """
    try:
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )
    except Exception:  # noqa: BLE001
        return "- workspace_agent: default fallback agent."

    lines: List[str] = []
    for name in sorted(AgentRegistry.list_agents()):
        cls = AgentRegistry.get_agent_class(name)
        if cls is None:
            continue
        profile = getattr(cls, "profile", {}) or {}
        summary = (profile.get("summary") or cls.__doc__ or name).strip()
        # Keep each line short — the planner doesn't need the full
        # capabilities array, just enough to disambiguate domains.
        first_sentence = summary.split(".")[0].strip()
        lines.append(f"- {name}: {first_sentence}.")
    return "\n".join(lines) if lines else "- workspace_agent: default fallback agent."


def _build_system_prompt() -> str:
    """Substitute the live agent catalog into the system prompt."""
    return SYSTEM_PROMPT_TEMPLATE.format(agent_catalog=_build_agent_catalog())


# Resolved at import time so tests can monkeypatch ``SYSTEM_PROMPT``.
# Re-resolved per-request inside ``plan_with_llm`` so a newly-registered
# agent (e.g. one added during a long-running process) joins the catalog
# automatically.
SYSTEM_PROMPT = _build_system_prompt()

PROJECT_SYSTEM_PROMPT = _PromptRegistry.get("planner.project")

TASK_SYSTEM_PROMPT = _PromptRegistry.get("planner.task")

GENERIC_TASK_TITLES = {
    "define scope and success criteria",
    "collect requirements and constraints",
    "draft work breakdown and milestones",
    "estimate budget and resources",
    "assign owners and due dates",
    "final review and next steps",
}


def _normalize_task_title(title: str, project_title: str | None) -> str:
    cleaned = (title or "").strip()
    if project_title:
        prefix = project_title.strip().lower()
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(project_title):].lstrip(":-–— ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


def _tasks_need_regeneration(tasks: List[TaskSpec], project_title: Optional[str]) -> bool:
    if not tasks:
        return True
    if len(tasks) < 6 or len(tasks) > 12:
        return True
    normalized = [_normalize_task_title(task.title, project_title) for task in tasks]
    generic_hits = sum(1 for title in normalized if title in GENERIC_TASK_TITLES)
    return (generic_hits / max(len(normalized), 1)) >= 0.6


def _resolve_model_name(llm: Any, fallback: Optional[str]) -> str:
    """Best-effort model-name extraction from a LangChain chat model.

    Different providers expose the model id under different attributes
    (``model_name`` for OpenAI, ``deployment_name`` for Azure, ``model``
    for some). We try the common ones and fall back to whatever the
    caller passed in. Returns an empty string when nothing is available
    so callers can write the field as ``""`` rather than ``None``.
    """
    for attr in ("model_name", "model", "deployment_name", "deployment"):
        value = getattr(llm, attr, None)
        if isinstance(value, str) and value:
            return value
    return fallback or ""


def _resolve_token_counts(response: Any) -> Tuple[Optional[int], Optional[int]]:
    """Pull ``(prompt_tokens, completion_tokens)`` off an LLM response.

    LangChain's modern API attaches a ``usage_metadata`` dict (with
    ``input_tokens`` and ``output_tokens`` keys) to ``AIMessage``
    instances. Older shims live under ``response_metadata.token_usage``
    with ``prompt_tokens`` / ``completion_tokens``. Try both before
    giving up; an unknown count is preferable to a wrong one, so we
    return ``None`` when nothing parses.
    """
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        prompt = usage.get("input_tokens")
        completion = usage.get("output_tokens")
        return (
            int(prompt) if isinstance(prompt, (int, float)) else None,
            int(completion) if isinstance(completion, (int, float)) else None,
        )

    response_metadata = getattr(response, "response_metadata", None) or {}
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, dict):
            prompt = token_usage.get("prompt_tokens")
            completion = token_usage.get("completion_tokens")
            return (
                int(prompt) if isinstance(prompt, (int, float)) else None,
                int(completion) if isinstance(completion, (int, float)) else None,
            )
    return (None, None)


def _log_llm_call(
    *,
    plan_id: str,
    system_prompt: str,
    user_prompt: str,
    response_text: str,
    model_used: str,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    latency_ms: int,
) -> None:
    """Persist a DeepRunLog row recording one planner LLM invocation.

    Failure-safe: this function exists so prompt-engineering iteration
    has the data it needs (the actual prompt the model saw, the actual
    response, token counts, latency, cost). It is **observation only**
    — it must never raise, because a logging error here would crash
    the planner. Any DB / lookup failure is swallowed and the request
    continues.

    The cost is computed at write time from the seeded
    ``AIModel.input_cost_per_1k`` / ``output_cost_per_1k`` values.
    When the model is missing pricing rows, ``cost_usd`` stays
    ``NULL`` so the dashboard does not falsely report ``$0.00``.
    """
    try:
        from decimal import Decimal

        from infrastructure.persistence.ai.agents.models import (
            DeepRun,
            DeepRunLog,
        )
        from infrastructure.persistence.ai.llms.models import AIModel

        run = DeepRun.objects.filter(plan_id=plan_id).first()
        if run is None:
            # No DeepRun row yet (CLI / tests / pre-creation paths).
            # Skip silently — no useful row to attach the log to.
            return

        cost_usd = None
        if model_used and prompt_tokens is not None and completion_tokens is not None:
            ai_model = AIModel.objects.filter(model_id=model_used).first()
            if ai_model is not None:
                cost_usd = (
                    (Decimal(prompt_tokens) / Decimal(1000))
                    * ai_model.input_cost_per_1k
                    + (Decimal(completion_tokens) / Decimal(1000))
                    * ai_model.output_cost_per_1k
                )

        DeepRunLog.objects.create(
            deep_run=run,
            event_type="llm_call",
            agent_type="planner",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            llm_response=response_text,
            model_used=model_used or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
    except Exception:  # noqa: BLE001
        # Observability must not break the request path. The planner
        # has its own retry + fallback for malformed plans, but those
        # protect the caller, not the logger. Swallow here.
        logger.debug(
            "Failed to log planner LLM call for plan_id=%s",
            plan_id,
            exc_info=True,
        )


def _parse_task_items(raw: str) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if isinstance(parsed, dict):
        items = parsed.get("tasks") or []
    elif isinstance(parsed, list):
        items = parsed
    else:
        items = []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _coerce_priority(value: str | None) -> Priority:
    if not value:
        return Priority.medium
    text = str(value).strip().lower()
    return Priority(text) if text in Priority._value2member_map_ else Priority.medium


def _coerce_status(value: str | None) -> TaskStatus:
    if not value:
        return TaskStatus.todo
    text = str(value).strip().lower()
    return TaskStatus(text) if text in TaskStatus._value2member_map_ else TaskStatus.todo


def _build_task_specs(items: List[Dict[str, Any]], project_title: Optional[str]) -> List[TaskSpec]:
    tasks: List[TaskSpec] = []
    seen = set()
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        normalized = _normalize_task_title(title, project_title)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tasks.append(
            TaskSpec(
                title=normalized.title(),
                description=item.get("description"),
                priority=_coerce_priority(item.get("priority")),
                status=_coerce_status(item.get("status")),
            )
        )
    return tasks


def _generate_contextual_tasks(
    *,
    goal: str,
    project_title: Optional[str],
    budget_lines: List[BudgetLine],
    workspace_id: Optional[str],
    team_id: Optional[str],
    model_name: Optional[str],
) -> List[TaskSpec]:
    from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

    llm = LLMFactory.get_llm(model_name=model_name)
    payload = {
        "title": project_title or "",
        "goal": goal,
        "estimate_items": [
            {"label": line.label, "amount": line.amount, "category": (line.metadata or {}).get("category_name")}
            for line in budget_lines
        ],
    }
    messages = [
        SystemMessage(content=TASK_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload)),
    ]
    raw = llm.invoke(messages)
    content = getattr(raw, "content", "") or ""
    items = _parse_task_items(content)
    return _build_task_specs(items, project_title)


def plan_with_llm(
    goal: str,
    *,
    plan_id: str,
    workspace_id: Optional[str] = None,
    team_id: Optional[str] = None,
    model_name: Optional[str] = None,
    sector_slug: Optional[str] = None,
    deep_pack: Optional[str] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> PlanSpec:
    """
    Call the LLM to generate a PlanSpec for the given goal.

    Falls back to an empty plan if parsing fails.
    """
    from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

    context = dict(extra_context or {})
    if sector_slug:
        context.setdefault("sector", sector_slug)
    if deep_pack:
        context.setdefault("deep_pack", deep_pack)

    llm = LLMFactory.get_llm(model_name=model_name)
    user_payload = json.dumps({"goal": goal, "workspace_id": workspace_id, "team_id": team_id, "context": context})

    # Re-resolve the system prompt per call so a newly-registered agent
    # (added after the module first imported) joins the catalog without
    # a process restart.
    system_prompt = _build_system_prompt()

    def _call(extra_system: str = "") -> List[Dict[str, Any]]:
        full_system_prompt = (
            system_prompt + (("\n" + extra_system) if extra_system else "")
        )
        messages = [
            SystemMessage(content=full_system_prompt),
            HumanMessage(content=user_payload),
        ]
        # Time the round-trip so the DeepRunLog row records latency.
        # Failure-safe: if the invoke raises, we still try to log a
        # row recording the failure before letting the planner's
        # existing retry path handle it.
        started_at = time.perf_counter()
        try:
            raw = llm.invoke(messages)
        except Exception:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            _log_llm_call(
                plan_id=plan_id,
                system_prompt=full_system_prompt,
                user_prompt=user_payload,
                response_text="",
                model_used=_resolve_model_name(llm, model_name),
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=latency_ms,
            )
            raise
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        text = getattr(raw, "content", "") or ""
        prompt_tokens, completion_tokens = _resolve_token_counts(raw)
        _log_llm_call(
            plan_id=plan_id,
            system_prompt=full_system_prompt,
            user_prompt=user_payload,
            response_text=text,
            model_used=_resolve_model_name(llm, model_name),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
        try:
            parsed = json.loads(text)
        except Exception:
            return []
        if isinstance(parsed, dict) and isinstance(parsed.get("tasks"), list):
            return parsed["tasks"]
        return []

    tasks = _call()

    # Validate against PlanSpec via build_plan_from_actions; if the result
    # has zero tasks, retry once with a stricter reminder. This catches
    # both invalid JSON and shape mismatches without crashing the run.
    plan = build_plan_from_actions(plan_id=plan_id, goal=goal, actions=tasks)
    if not plan.tasks:
        tasks = _call(
            "REMINDER: Output MUST be valid JSON of shape {\"tasks\": [...]}. "
            "Each task object MUST include `title`, `priority`, and "
            "`agent_type` (one of the registered agents in the catalog). "
            "Do not include any prose, only the JSON object."
        )
        plan = build_plan_from_actions(plan_id=plan_id, goal=goal, actions=tasks)
    # Backfill workspace/team on tasks if provided at the call level.
    for task in plan.tasks:
        if workspace_id and not task.workspace_id:
            task.workspace_id = workspace_id
        if team_id and not task.team_id:
            task.team_id = team_id
    if sector_slug:
        plan.metadata.setdefault("sector", sector_slug)
    if deep_pack:
        plan.metadata.setdefault("deep_pack", deep_pack)
    return plan


def plan_project_with_llm(
    goal: str,
    *,
    plan_id: str,
    workspace_id: Optional[str] = None,
    team_id: Optional[str] = None,
    project_title: Optional[str] = None,
    model_name: Optional[str] = None,
    sector_slug: Optional[str] = None,
    deep_pack: Optional[str] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> PlanSpec:
    """
    Call the LLM to generate a project plan with tasks and budget lines.
    """
    from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

    context = dict(extra_context or {})
    if sector_slug:
        context.setdefault("sector", sector_slug)
    if deep_pack:
        context.setdefault("deep_pack", deep_pack)

    llm_available = True
    try:
        llm = LLMFactory.get_llm(model_name=model_name)
        payload = {
            "goal": goal,
            "workspace_id": workspace_id,
            "team_id": team_id,
            "project_title": project_title,
            "context": context,
        }
        messages = [
            SystemMessage(content=PROJECT_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload)),
        ]
        raw = llm.invoke(messages)
        content = getattr(raw, "content", "") or ""
    except Exception:
        llm_available = False
        content = ""

    tasks: List[Dict[str, Any]] = []
    budget_lines: List[BudgetLine] = []
    resolved_title = project_title or ""
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            if isinstance(parsed.get("tasks"), list):
                tasks = parsed["tasks"]
            if isinstance(parsed.get("budget_lines"), list):
                for line in parsed["budget_lines"]:
                    if not isinstance(line, dict):
                        continue
                    label = str(line.get("label") or "").strip()
                    amount = line.get("amount")
                    if not label or amount is None:
                        continue
                    try:
                        amount_value = float(amount)
                    except (TypeError, ValueError):
                        continue
                    budget_lines.append(
                        BudgetLine(
                            label=label,
                            amount=amount_value,
                            description=line.get("description"),
                            metadata=line.get("metadata") or {},
                        )
                    )
            if parsed.get("project_title"):
                resolved_title = str(parsed.get("project_title")).strip()
    except Exception:
        tasks = []
        budget_lines = []

    if not tasks:
        from .project import draft_project_plan

        fallback_title = resolved_title or goal or "Project"
        resolved_title = fallback_title
        plan = draft_project_plan(
            project_title=fallback_title,
            goal=goal,
            workspace_id=workspace_id or "",
        )
        if budget_lines:
            plan.budget_lines = budget_lines
    else:
        plan = build_plan_from_actions(plan_id=plan_id, goal=goal, actions=tasks)

    cleaned_tasks: List[TaskSpec] = []
    for task in plan.tasks:
        normalized = _normalize_task_title(task.title, resolved_title or project_title)
        if not normalized:
            continue
        task.title = normalized.title()
        cleaned_tasks.append(task)
    if cleaned_tasks:
        plan.tasks = cleaned_tasks

    if llm_available and _tasks_need_regeneration(plan.tasks, resolved_title or project_title):
        try:
            contextual_tasks = _generate_contextual_tasks(
                goal=goal,
                project_title=resolved_title or project_title,
                budget_lines=budget_lines,
                workspace_id=workspace_id,
                team_id=team_id,
                model_name=model_name,
            )
        except Exception:
            contextual_tasks = []
        if contextual_tasks:
            plan.tasks = contextual_tasks

    for task in plan.tasks:
        if workspace_id and not task.workspace_id:
            task.workspace_id = workspace_id
        if team_id and not task.team_id:
            task.team_id = team_id

    if budget_lines:
        plan.budget_lines = budget_lines
    if resolved_title:
        plan.metadata["project_title"] = resolved_title
    if workspace_id:
        plan.metadata.setdefault("workspace_id", workspace_id)
    if team_id:
        plan.metadata.setdefault("team_id", team_id)
    if sector_slug:
        plan.metadata.setdefault("sector", sector_slug)
    if deep_pack:
        plan.metadata.setdefault("deep_pack", deep_pack)
    return plan
