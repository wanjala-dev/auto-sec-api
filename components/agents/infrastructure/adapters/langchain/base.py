"""
Base Agent Framework

Provides the foundation for all AI agents with common functionality,
state management, and LangChain integration.
"""

import functools
import json
import logging
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from typing import Any, Union

# LangChain 1.x — the tool-calling agent graph. `create_agent` replaces the
# 0.3 `AgentExecutor` + `create_react_agent` / `create_tool_calling_agent`
# construction. See docs/plans/LANGCHAIN_1X_MIGRATION_2026-07-18.md.
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, Tool
from langchain_core.tools.base import BaseTool

from components.agents.application.ports.llm_provider_port import LLMProviderPort
from components.agents.application.ports.tracing_port import NullTracingAdapter, TracingPort
from components.agents.infrastructure.adapters.langchain.graph_agent import build_graph_executor
from components.agents.infrastructure.adapters.langchain.memory_service import (
    get_agent_memory_service,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Agent decorator framework (ADR 0003)
#
# `@register_agent`, `@tool`, `@requires_role`, and the `ToolResult` dataclass
# let new agents be authored in a single file with no edits to existing code.
# Existing agents that override `_setup_tools` continue to work unchanged —
# the new default `_setup_tools()` body only runs when a subclass uses the
# decorator pattern instead.
#
# See `docs/adr/0003-agent-decorator-framework.md` for the full rationale.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ToolResult:
    """Consistent return shape for `@tool`-decorated agent methods.

    Tools can return any type — when they return a `ToolResult`, the
    framework calls `.serialize()` to produce a string the LLM can read.
    Strings, dicts, and other primitives are passed through as-is.
    """

    ok: bool = True
    message: str = ""
    data: dict[str, Any] | None = None
    error: str | None = None

    def serialize(self) -> str:
        if not self.ok:
            return f"Error: {self.error or self.message or 'unknown error'}"
        if self.data is not None:
            try:
                return f"{self.message}\n{json.dumps(self.data, default=str)}".strip()
            except (TypeError, ValueError):
                return f"{self.message}\n{self.data}".strip()
        return self.message or "OK"


def tool(
    name: str | None = None,
    description: str | None = None,
    args_schema: type | None = None,
    risk: str | None = None,
):
    """Mark a method on a `BaseAgent` subclass as an LLM-invocable tool.

    The base class's `__init_subclass__` collects every method tagged with
    `_agent_tool_meta` at class definition time and the default
    `_setup_tools()` promotes them to `langchain.tools.Tool` instances.

    Defaults: `name` falls back to the method name, `description` falls
    back to the method's docstring. `args_schema` is an optional Pydantic
    model that gives the LLM a typed argument list.
    """

    def decorator(func):
        func._agent_tool_meta = {
            "name": name or func.__name__,
            "description": description or (func.__doc__ or "").strip() or func.__name__,
            "args_schema": args_schema,
            # SEE-203 — risk tier (None normalizes to "read" at the gate).
            "risk": risk,
        }
        return func

    return decorator


# ── LLM-friendly tool input adapter (PR-I bug A fix, 2026-05-09) ────────
#
# Every legacy tool method on the agents follows this shape:
#
#     @tool(...)
#     def list_sponsors(self, input_str: str) -> str:
#         data = _coerce_payload(input_str)  # accepts dict, JSON, or text
#         ...
#
# That means each tool's *body* already accepts arbitrary structured
# input — but ``StructuredTool.from_function`` infers a strict pydantic
# schema (``{input_str: str}``) from the method signature. When the
# planner LLM reads the docstring's "Optional input as JSON: {active:
# bool, ...}" hint and helpfully passes ``{"active": True}`` directly,
# pydantic rejects with "input_str: Field required" and the tool never
# runs — it surfaces in chat as a generic "validation error" the LLM
# can't recover from.
#
# Fix: a permissive args_schema that accepts ``input_str`` AND any extra
# kwargs (``extra="allow"``). The wrapper folds extras into a JSON
# string, then calls the original tool with that single string. The
# tool body's existing ``_coerce_payload`` parses it back to a dict —
# the same shape the body always expected.
#
# This sits in the framework so all 16+ legacy ``input_str: str`` tools
# inherit the fix in one place. Tools with explicit ``args_schema``
# (typed Pydantic models) are not adapted — they already advertise their
# real shape to the LLM.
try:
    from pydantic import BaseModel as _PdModel
    from pydantic import ConfigDict as _PdConfigDict
except ImportError:  # pragma: no cover — pydantic v1 fallback
    from pydantic.v1 import BaseModel as _PdModel  # type: ignore

    _PdConfigDict = None


class LegacyStringToolInput(_PdModel):
    """Permissive args schema for legacy single-string tools."""

    input_str: str = ""

    if _PdConfigDict is not None:
        model_config = _PdConfigDict(extra="allow")
    else:  # pragma: no cover — pydantic v1

        class Config:  # type: ignore[no-redef]
            extra = "allow"


def _adapt_legacy_tool(bound):
    """Wrap a legacy single-positional-string tool method so it accepts
    arbitrary kwargs from a tool-calling LLM."""

    @functools.wraps(bound)
    def adapter(input_str: str = "", **extras):
        if extras:
            # LLM passed structured kwargs. JSON-encode them so the tool
            # body's ``_coerce_payload`` can parse back to a dict. If
            # ``input_str`` was *also* supplied, prefer the structured
            # kwargs — they're the explicit data.
            payload = json.dumps(extras)
        else:
            payload = input_str or ""
        return bound(payload)

    return adapter


class _GraphExecutorHandle:
    """Adapts a LangChain 1.x ``create_agent`` graph to the legacy
    ``AgentExecutor.invoke`` contract the rest of ``BaseAgent`` expects.

    ``execute()`` calls ``self.agent_executor.invoke({"input": query})`` and
    reads ``result["output"]`` + ``result["intermediate_steps"]``. The 1.x
    graph instead speaks ``{"messages": [...]}`` in and out. This handle
    translates both directions so the migration is confined to the executor
    seam:

      - IN:  ``{"input": q}`` → ``{"messages": [*history, HumanMessage(q)]}``
      - OUT: final answer  = ``result["messages"][-1].content``
             intermediate  = ``(AgentAction-like, observation)`` pairs
                             reconstructed from ``AIMessage.tool_calls`` +
                             the following ``ToolMessage`` so
                             ``_persist_tool_observations`` keeps working.

    Conversation memory (the 0.3 ``ConversationBufferMemory`` replacement):
    ``history_provider`` returns the SQL-persisted window of prior messages
    (``BaseAgent.memory.load_messages()``), which is threaded into the graph
    input on every invoke. Persistence of the NEW turn stays where it always
    was — ``memory_service.record_execution`` in ``execute()`` — so there is
    exactly one durable store (Postgres) and no process-local checkpointer
    that would silently fork the conversation across workers.

    ``AgentTestCase`` never sees this class — it overwrites
    ``self.agent_executor`` with its own scripted stub — so unit tests are
    untouched. ``.callbacks`` is exposed so the ``execute()`` Langfuse-flush
    loop still finds the run callbacks.
    """

    def __init__(
        self,
        *,
        graph,
        callbacks=None,
        recursion_limit: int = 50,
        history_provider=None,
        rubric_provider=None,
    ):
        self._graph = graph
        self.callbacks = list(callbacks or [])
        self._recursion_limit = recursion_limit
        self._history_provider = history_provider
        self._rubric_provider = rubric_provider

    def _build_config(self) -> dict:
        config: dict[str, Any] = {"recursion_limit": self._recursion_limit}
        if self.callbacks:
            config["callbacks"] = self.callbacks
        return config

    def _load_history(self) -> list[BaseMessage]:
        """Prior-turn messages from the durable SQL store (windowed).

        Degrades to an empty history on any failure — a memory outage must
        never take down the chat turn itself.
        """
        if not callable(self._history_provider):
            return []
        try:
            history = self._history_provider() or []
        except Exception:
            logger.warning("history_provider failed; invoking without prior context", exc_info=True)
            return []
        return [msg for msg in history if isinstance(msg, BaseMessage)]

    def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = inputs.get("input", "") if isinstance(inputs, dict) else str(inputs)
        state: dict[str, Any] = {"messages": [*self._load_history(), HumanMessage(content=query)]}
        # deepagents.RubricMiddleware activates via the invocation state:
        # with no "rubric" key it is a no-op. The provider returns the
        # agent-type rubric only when the middleware is attached + enabled.
        if callable(self._rubric_provider):
            try:
                rubric = self._rubric_provider()
            except Exception:
                rubric = None
            if rubric:
                state["rubric"] = rubric
        result = self._graph.invoke(state, config=self._build_config())
        messages = result.get("messages", []) if isinstance(result, dict) else []
        output = ""
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if isinstance(msg, AIMessage) and content and not getattr(msg, "tool_calls", None):
                output = content if isinstance(content, str) else str(content)
                break
        if not output and messages:
            last = messages[-1]
            output = getattr(last, "content", "") or ""
        return {
            "input": query,
            "output": output,
            "intermediate_steps": self._reconstruct_intermediate_steps(messages),
        }

    @staticmethod
    def _reconstruct_intermediate_steps(messages) -> list:
        """Rebuild ``[(AgentAction-like, observation)]`` pairs from the
        graph transcript so ``_persist_tool_observations`` (which unpacks
        ``step[0].tool`` / ``step[0].tool_input`` / ``step[1]``) still logs
        each tool call to DeepRunLog."""
        from types import SimpleNamespace

        # Map tool_call_id → tool output from ToolMessages.
        observations: dict[str, Any] = {}
        for msg in messages:
            if isinstance(msg, ToolMessage):
                observations[getattr(msg, "tool_call_id", "")] = getattr(msg, "content", "")

        steps = []
        for msg in messages:
            tool_calls = getattr(msg, "tool_calls", None) if isinstance(msg, AIMessage) else None
            if not tool_calls:
                continue
            for call in tool_calls:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
                args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
                call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")
                action = SimpleNamespace(
                    tool=name,
                    tool_input=args,
                    log=f"Invoking {name} with {args}",
                )
                steps.append((action, observations.get(call_id, "")))
        return steps


def register_agent(name: str, aliases: tuple[str, ...] = ()):
    """Register an agent class in the `AgentRegistry` at class definition time.

    Replaces the manual `AgentRegistry.register("name", BlogAgent)` block at
    the bottom of `base.py`. Each name + alias is registered idempotently;
    re-registering the same name with a different class logs a WARNING so
    accidental shadowing is diagnosable.
    """

    def decorator(cls):
        # Pin the canonical slug on the class so a lookup by alias can
        # resolve back to the registered name. The chat-header display
        # reads this (via ``AgentRegistry.canonical_name_for``) so the
        # surface always shows ``writing_agent`` rather than whichever
        # alias the planner picked (``letter_agent`` etc.).
        cls._canonical_agent_name = name
        all_names = (name,) + tuple(aliases)
        for entry in all_names:
            existing = AgentRegistry._agents.get(entry)
            if existing is not None and existing is not cls:
                logger.warning(
                    "Overwriting agent registration: %s was %s, now %s",
                    entry,
                    existing.__name__,
                    cls.__name__,
                )
            AgentRegistry.register(entry, cls)
        return cls

    return decorator


def requires_role(*allowed_roles: str):
    """Restrict a `@tool`-decorated method to actors with a matching
    `WorkspaceMembership.role` for the agent's workspace.

    Owners always pass even without an explicit membership row. Staff /
    superusers also pass for support workflows. Everyone else gets a
    refusal string the LLM surfaces gracefully.

    Permission decisions read `role` only — never persona. See ADR 0002.
    """

    allowed = set(allowed_roles)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            from infrastructure.persistence.workspaces.models import (
                Workspace,
                WorkspaceMembership,
            )

            user_id = getattr(self, "user_id", None)
            workspace_id = getattr(self, "workspace_id", None)
            if not user_id or not workspace_id:
                return "You don't have permission to perform this action."

            try:
                # SEE-201 — the autonomous AI service principal never
                # self-executes a permission-gated action; it surfaces a
                # finding for a human instead. Checked before the owner /
                # membership resolution so the cap holds even if the AI user
                # is later granted a membership row.
                if is_ai_service_principal(user_id, workspace_id):
                    return (
                        "Autonomous AI runs cannot perform this action "
                        "directly. Surface it as a finding for a workspace "
                        "admin to review."
                    )
                if Workspace.objects.filter(id=workspace_id, workspace_owner_id=user_id).exists():
                    return func(self, *args, **kwargs)
                has_role = WorkspaceMembership.objects.filter(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    status=WorkspaceMembership.Status.ACTIVE,
                    role__in=allowed,
                ).exists()
            except Exception as exc:
                logger.warning(
                    "requires_role check failed for %s: %s",
                    func.__name__,
                    exc,
                )
                return "You don't have permission to perform this action."

            if not has_role:
                return "You don't have permission to perform this action."
            return func(self, *args, **kwargs)

        return wrapper

    return decorator


def resolve_workspace_role(user_id, workspace_id):
    """Return the effective ``WorkspaceMembership`` role of *user* in *workspace*.

    Mirrors the resolution ``requires_role`` uses (ADR 0002 — role, never
    persona): the workspace owner resolves to ``"owner"`` even without a
    membership row; otherwise the active membership's role; ``None`` when the
    actor has no active membership. Callers pass this to a retrieval port as
    ``viewer_role`` so results are scoped to the tiers the actor may read
    (SEE-199). ``None`` is least-privilege — a caller that can't resolve a role
    gets GENERAL-only retrieval, never restricted facts.
    """
    if not user_id or not workspace_id:
        return None
    from infrastructure.persistence.workspaces.models import (
        Workspace,
        WorkspaceMembership,
    )

    try:
        # SEE-201 — the autonomous AI service principal is a trusted internal
        # reader (the detector needs restricted facts to surface findings), so
        # it reads every tier. Its write/action cap lives in ``requires_role``.
        if is_ai_service_principal(user_id, workspace_id):
            return "ai_service"
        if Workspace.objects.filter(id=workspace_id, workspace_owner_id=user_id).exists():
            return "owner"
        return (
            WorkspaceMembership.objects.filter(
                workspace_id=workspace_id,
                user_id=user_id,
                status=WorkspaceMembership.Status.ACTIVE,
            )
            .values_list("role", flat=True)
            .first()
        )
    except Exception as exc:
        logger.warning(
            "resolve_workspace_role failed user_id=%s workspace_id=%s: %s",
            user_id,
            workspace_id,
            exc,
        )
        return None


def is_ai_service_principal(user_id, workspace_id) -> bool:
    """True when *user_id* is the workspace's autonomous AI service user.

    The AI teammate user (``AITeammateProfile.user``) runs the scheduled
    detector. It is a trusted internal *reader* but must never self-execute a
    permission-gated action — it surfaces findings for a human instead
    (SEE-201). Identity is the profile's user, independent of any
    ``WorkspaceMembership``, so the write cap holds even if the AI is later
    granted a membership row.
    """
    if not user_id or not workspace_id:
        return False
    from infrastructure.persistence.ai.models import AITeammateProfile

    try:
        return AITeammateProfile.objects.filter(workspace_id=workspace_id, user_id=user_id).exists()
    except Exception as exc:
        logger.warning(
            "is_ai_service_principal check failed user_id=%s workspace_id=%s: %s",
            user_id,
            workspace_id,
            exc,
        )
        return False


def _risk_gated(func, tool_name, explicit_risk, agent):
    """Wrap a promoted tool so its risk tier is enforced per call (SEE-203).

    An autonomous run is denied ``irreversible`` tools; an ``irreversible`` tool
    is denied to any caller until this run carries ``approval_granted``. Both
    return a refusal string the LLM surfaces gracefully — the tool body never
    runs. Reversible/read tools pass straight through.
    """
    from components.agents.application.policies.tool_risk import (
        resolve_tool_risk,
        tool_risk_refusal,
    )

    resolved_risk = resolve_tool_risk(tool_name, explicit_risk)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            is_autonomous = is_ai_service_principal(
                getattr(agent, "user_id", None), getattr(agent, "workspace_id", None)
            )
            approval_granted = bool((getattr(agent, "config", None) or {}).get("approval_granted"))
        except Exception:
            is_autonomous, approval_granted = False, False
        refusal = tool_risk_refusal(resolved_risk, is_autonomous=is_autonomous, approval_granted=approval_granted)
        if refusal is not None:
            return refusal
        return func(*args, **kwargs)

    return wrapper


# Status string constants (avoids importing the AgentExecution ORM model).
EXECUTION_STATUS_COMPLETED = "completed"
EXECUTION_STATUS_FAILED = "failed"

_retry_candidates: list[type[BaseException]] = []

# Lazy singleton for the default tracing adapter.
_default_tracing: TracingPort | None = None


def _default_tracing_port() -> TracingPort:
    """
    Resolve the default TracingPort.

    Tries to load the Langfuse adapter; falls back to the null adapter
    so agent creation never fails due to a missing tracing backend.
    """
    global _default_tracing
    if _default_tracing is None:
        try:
            from components.agents.infrastructure.adapters.tracing.langfuse import (
                LangfuseTracingAdapter,
            )

            adapter = LangfuseTracingAdapter()
            _default_tracing = adapter if adapter.is_available() else NullTracingAdapter()
        except Exception:
            logger.debug("Langfuse adapter unavailable, using NullTracingAdapter")
            _default_tracing = NullTracingAdapter()
    return _default_tracing


try:  # pragma: no cover - optional dependency
    from requests.exceptions import (
        ChunkedEncodingError,
    )
    from requests.exceptions import (
        ConnectionError as RequestsConnectionError,
    )
    from requests.exceptions import (
        Timeout as RequestsTimeout,
    )
except Exception:  # pragma: no cover - requests may be absent in some environments
    ChunkedEncodingError = RequestsConnectionError = RequestsTimeout = None
else:
    _retry_candidates.extend([ChunkedEncodingError, RequestsConnectionError, RequestsTimeout])

try:  # pragma: no cover - optional dependency
    from urllib3.exceptions import ProtocolError
except Exception:  # pragma: no cover
    ProtocolError = None
else:
    _retry_candidates.append(ProtocolError)

try:  # pragma: no cover - OpenAI package variants
    from openai import error as openai_error  # type: ignore
except Exception:  # pragma: no cover - OpenAI may not be installed locally
    openai_error = None
else:
    for attr in (
        "APIConnectionError",
        "APITimeoutError",
        "ServiceUnavailableError",
        "RateLimitError",
    ):
        candidate = getattr(openai_error, attr, None)
        if candidate:
            _retry_candidates.append(candidate)

RETRYABLE_AGENT_EXCEPTIONS: tuple[type[BaseException], ...] = tuple(
    {candidate for candidate in _retry_candidates if candidate}
)


@dataclass
class AgentState:
    """Represents the current state of an agent"""

    agent_id: str
    user_id: str
    workspace_id: str
    current_step: int = 0
    total_steps: int = 0
    context: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    status: str = "initialized"  # initialized, running, completed, failed, paused

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for serialization"""
        return {
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "context": self.context,
            "results": self.results,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status,
        }


class BaseAgent(ABC):
    """
    Base class for all AI agents

    Provides common functionality for:
    - State management
    - Tool integration
    - Error handling
    - Progress tracking
    """

    # Optional class-level profile (ADR 0003). Subclasses set this to
    # advertise name / summary / capabilities / sample_prompts. The DB
    # row's `config["profile"]` overrides any field set here per workspace.
    profile: dict[str, Any] = {}

    @staticmethod
    def parse_tool_input(
        input_str, *, defaults: dict[str, Any] | None = None, text_key: str = "title"
    ) -> dict[str, Any]:
        """Normalize a `@tool` string argument into a dict.

        The LLM passes tool arguments as a single string that is USUALLY a JSON
        object but sometimes just bare text. Rather than every tool re-deriving
        the same ``try: json.loads(...) except: {"title": raw}`` block (a
        copy-paste that predates this helper — see the older triage tools), call
        this once:

            data = self.parse_tool_input(input_str, defaults={"severity": "medium"})

        - A JSON object string → parsed dict (merged over ``defaults``).
        - Any other non-empty string → ``{text_key: <the string>}`` (merged over
          ``defaults``) so bare-text calls still work.
        - Empty / None → a copy of ``defaults`` (or ``{}``).

        Keeps tool bodies focused on behaviour, not argument plumbing.
        """
        base = dict(defaults or {})
        raw = (input_str or "").strip()
        if not raw:
            return base
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    base.update(parsed)
                    return base
            except (ValueError, TypeError):
                pass
        base[text_key] = raw
        return base

    # Populated by `__init_subclass__`. List of (method_name, meta) for
    # every `@tool`-decorated method on the class (including those
    # inherited from mixins via MRO). The default `_setup_tools()`
    # promotes these to `langchain.tools.Tool` instances at __init__ time.
    _decorated_tools: list[tuple[str, dict[str, Any]]] = []

    def __init_subclass__(cls, **kwargs):
        """Walk the new subclass's MRO and collect every `@tool`-decorated
        method into `cls._decorated_tools`. De-dupes by tool name with
        leftmost-MRO-wins so subclasses can override an inherited tool by
        re-declaring a method with the same `@tool(name=...)`.
        """
        super().__init_subclass__(**kwargs)

        seen_names: dict[str, str] = {}  # tool name -> defining class name
        collected: list[tuple[str, dict[str, Any]]] = []

        for klass in cls.__mro__:
            if klass in (object, BaseAgent):
                continue
            for attr_name, attr_value in vars(klass).items():
                meta = getattr(attr_value, "_agent_tool_meta", None)
                if not meta:
                    continue
                tool_name = meta.get("name") or attr_name
                if tool_name in seen_names:
                    logger.debug(
                        "Tool '%s' on %s shadowed by earlier definition in %s",
                        tool_name,
                        klass.__name__,
                        seen_names[tool_name],
                    )
                    continue
                seen_names[tool_name] = klass.__name__
                collected.append((attr_name, meta))

        cls._decorated_tools = collected

    def __init__(
        self,
        agent_id: str,
        user_id: str,
        workspace_id: str,
        *,
        tracing_port: TracingPort | None = None,
        llm_provider: LLMProviderPort | None = None,
        telemetry_callback_factory: Any | None = None,
        **kwargs,
    ):
        self.agent_id = agent_id
        self.user_id = user_id
        self.workspace_id = workspace_id
        self._override_conversation_id: str | None = None
        self._tracing_port: TracingPort = tracing_port or _default_tracing_port()
        self._llm_provider: LLMProviderPort | None = llm_provider
        self._telemetry_callback_factory = telemetry_callback_factory

        # Persist incoming configuration for downstream use
        self.config: dict[str, Any] = dict(kwargs)
        self.department_id: str | None = self.config.get("department_id")

        # Initialize memory service
        self.memory_service = get_agent_memory_service(agent_id)

        self.state = AgentState(agent_id=agent_id, user_id=user_id, workspace_id=workspace_id)
        self.tools: list[BaseTool] = []
        self._all_tools: list[BaseTool] = []

        # Per-execution artifact collector. Tools that produce a
        # downloadable result (PDF report, generated file) call
        # ``self.collect_artifact({...})`` before returning their
        # response string. ``execute()`` clears this at the start of
        # each call and harvests it after the LLM finishes, so the
        # artifacts ride out on the assistant ``ConversationMessage``'s
        # ``metadata['artifacts']`` field. Frontend bubble reads that
        # to render a paperclip download icon.
        self._pending_artifacts: list[dict[str, Any]] = []

        # Use memory service instead of basic ConversationBufferMemory
        self.memory = self.memory_service.get_memory(
            memory_type=self.config.get("memory_type", "window"), window_size=self.config.get("window_size", 10)
        )

        self.telemetry_handler: Any | None = None

        # In 1.x this is a ``_GraphExecutorHandle`` wrapping a ``create_agent``
        # graph (or the ``AgentTestCase`` scripted stub). Typed ``Any`` because
        # the legacy ``AgentExecutor`` type no longer exists.
        self.agent_executor: Any | None = None
        self._graph_agent: Any | None = None  # the raw create_agent graph
        self.graph_executor: Any | None = None  # LangGraph StateGraph (opt-in)
        self._use_langgraph: bool = bool(self.config.get("use_langgraph", False))
        self._setup_agent(**kwargs)

    def _resolve_llm_provider(self) -> LLMProviderPort:
        """Lazily resolve the LLM provider, falling back to the default adapter."""
        if self._llm_provider is None:
            from components.agents.infrastructure.adapters.llm_provider_adapter import LLMFactoryAdapter

            self._llm_provider = LLMFactoryAdapter()
        return self._llm_provider

    def collect_artifact(self, artifact: dict[str, Any]) -> None:
        """Stash a downloadable artifact produced by a tool this turn.

        Tools that kick off PDF generation (financial / sponsorship /
        donation reports) call this with a dict the chat bubble can
        render as a paperclip download. ``execute()`` clears the
        collector at the start of each turn and forwards whatever was
        gathered into the assistant ``ConversationMessage``'s metadata
        before persisting.

        Expected dict shape (frontend contract):
        ``{kind: str, id: str, title: str, download_url: str,
        mime_type: str, status: str}``. ``status`` is typically
        ``"rendering"`` because PDF render runs async in Celery; the
        download endpoint itself returns 202 + retry-after if the file
        isn't ready yet. The frontend handles polling.

        Silently ignored if ``artifact`` isn't a dict — tools should
        not crash the response just because the collector got malformed
        input.
        """
        if isinstance(artifact, dict):
            self._pending_artifacts.append(dict(artifact))

    def _setup_agent(self, **kwargs):
        """Setup the agent with tools and executor"""
        # Initialize LLM via the injected port (no direct LLMFactory import)
        llm_port = self._resolve_llm_provider()
        self.llm = llm_port.get_llm(
            provider_slug=self.config.get("provider", "openai"),
            model_name=self.config.get("model_name", "gpt-4o-mini"),
            temperature=self.config.get("temperature", 0.1),  # Lower temperature for agents
        )

        # Setup tools
        self._setup_tools()
        self._all_tools = list(self.tools)

        # Create agent executor (legacy ReAct or modern LangGraph)
        self._create_agent_executor()

        # Optionally build LangGraph executor as an alternative
        if self._use_langgraph:
            self._build_graph_executor()

    def _setup_tools(self):
        """Setup agent-specific tools.

        Default behavior (ADR 0003): if the subclass declared any
        `@tool`-decorated methods, promote them to `langchain.tools.Tool`
        instances and assign to `self.tools`. Subclasses that need
        runtime-built tools (e.g. `DynamicAgent`) override this method
        and the override wins.

        Every agent — regardless of how it assembles its tools — gets a
        universal ``retrieve_workspace_context`` tool appended so grounded
        answers about the active workspace are always one call away.

        If `self.tools` is already populated by the time we get here
        (e.g. a subclass set it in `__init__` before calling super), we
        leave the agent-specific tools alone and only append the
        retrieval tool.
        """
        if not self.tools and getattr(type(self), "_decorated_tools", None):
            promoted = []
            for method_name, meta in type(self)._decorated_tools:
                bound = getattr(self, method_name, None)
                if not callable(bound):
                    continue
                # Build a StructuredTool — the tool-calling agent path
                # needs typed schemas to dispatch arguments correctly.
                # ``StructuredTool.from_function`` infers the schema from
                # the bound method's signature (e.g. ``input_str: str``),
                # producing a single-field pydantic model the LLM's
                # function-calling API can populate. An explicit
                # ``args_schema`` from ``@tool(...)`` overrides inference.
                #
                # Legacy single-string tools (the vast majority — 16+
                # across the agents whose method signature is
                # ``def foo(self, input_str: str)``) get adapted via
                # ``_adapt_legacy_tool`` + the permissive
                # ``LegacyStringToolInput`` schema. This lets the LLM
                # pass either ``{input_str: "..."}`` or arbitrary
                # kwargs like ``{active: true}``. Without this,
                # pydantic rejects kwargs with "input_str: Field
                # required" and chat surfaces a generic "validation
                # error" the LLM can't recover from. Tools that
                # supplied an explicit ``args_schema`` use the bound
                # function as-is — they advertise their real shape.
                explicit_schema = meta.get("args_schema")
                if explicit_schema is not None:
                    func_to_register = bound
                    schema_to_register = explicit_schema
                else:
                    func_to_register = _adapt_legacy_tool(bound)
                    schema_to_register = LegacyStringToolInput
                func_to_register = _risk_gated(
                    func_to_register,
                    meta.get("name") or method_name,
                    meta.get("risk"),
                    self,
                )
                promoted.append(
                    StructuredTool.from_function(
                        func=func_to_register,
                        name=meta.get("name") or method_name,
                        description=meta.get("description") or method_name,
                        args_schema=schema_to_register,
                    )
                )
            self.tools = promoted

        # Universal RAG tool — every agent can ground answers in the
        # indexed workspace snapshot.  Subclasses that declare a tool
        # with the same name win (leftmost-MRO-wins is enforced by the
        # decorator collector).
        if not any(getattr(t, "name", None) == "retrieve_workspace_context" for t in self.tools):
            self.tools.append(self._build_workspace_retrieval_tool())

    def _build_workspace_retrieval_tool(self) -> Tool:
        """Return the ``retrieve_workspace_context`` tool bound to this agent."""

        TOOL_NAME = "retrieve_workspace_context"

        def _retrieve(query: str) -> str:
            from components.agents.application.services.deep_run_context import (
                noop_context,
            )
            from components.knowledge.application.providers.workspace_retrieval_provider import (
                workspace_retrieval,
            )

            # When this tool runs inside a deep agent run, ``self`` has
            # the run's DeepRunContext stashed; outside a run it's
            # None. Falling back to the no-op context means tool code
            # below is uniform — every emit goes somewhere.
            ctx = getattr(self, "_active_deep_run_context", None) or noop_context()

            query_text = (query or "").strip()
            if not query_text:
                return (
                    "retrieve_workspace_context requires a non-empty query — "
                    "pass a short natural-language description of what you need."
                )
            ctx.info(
                f"Searching workspace knowledge for: {query_text!r}",
                tool_name=TOOL_NAME,
            )
            ctx.report_progress(20, 100, tool_name=TOOL_NAME)
            # Tier 3 #9 — rewrite the query before search.  Short
            # queries like "tldr" land closer to the snapshot chunks
            # when expanded into mission / activity keywords.  The
            # rewriter caches per (workspace_id, query) and falls
            # back to the raw query on any error.
            try:
                from components.knowledge.application.use_cases.rewrite_query_for_retrieval_use_case import (
                    RewriteQueryForRetrievalUseCase,
                )

                search_query = RewriteQueryForRetrievalUseCase().rewrite(
                    workspace_id=str(self.workspace_id),
                    query=query_text,
                )
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "retrieve_workspace_context: rewriter failed, using raw query",
                    exc_info=True,
                )
                search_query = query_text
            # Tier 3 #10 — over-fetch then rerank.  Ask pgvector for
            # k * 4 candidates under cosine, then a cross-encoder
            # reranker re-scores them against the original query_text
            # (not the rewritten one) and returns the best k.
            # Reranker errors fall back to original cosine order
            # truncated to k.
            try:
                from components.knowledge.application.use_cases.rerank_retrieved_chunks_use_case import (
                    DEFAULT_FETCH_MULTIPLIER,
                    RerankRetrievedChunksUseCase,
                )

                candidates = workspace_retrieval().search(
                    workspace_id=str(self.workspace_id),
                    query=search_query,
                    k=5 * DEFAULT_FETCH_MULTIPLIER,
                    # SEE-199 — scope retrieval to what the invoking actor's
                    # role may read, so a member can't pull owner/admin-only
                    # rollups through the agent's broad retrieval.
                    viewer_role=resolve_workspace_role(
                        getattr(self, "user_id", None),
                        self.workspace_id,
                    ),
                )
                chunks = RerankRetrievedChunksUseCase().rerank(
                    query=query_text,
                    chunks=candidates,
                    top_k=5,
                )
            except Exception:
                logger.exception(
                    "retrieve_workspace_context failed for workspace %s",
                    self.workspace_id,
                )
                ctx.warn(
                    "Retrieval backend unavailable — answering without indexed context.",
                    tool_name=TOOL_NAME,
                )
                return (
                    "retrieve_workspace_context: retrieval backend "
                    "unavailable — answer from other tools or say you "
                    "don't know."
                )

            if not chunks:
                ctx.warn(
                    "No indexed context for this workspace yet.",
                    tool_name=TOOL_NAME,
                )
                ctx.report_progress(100, 100, tool_name=TOOL_NAME)
                return (
                    "retrieve_workspace_context: no indexed context for "
                    "this workspace yet. Answer from other tools or say "
                    "you don't have that information."
                )

            total_chars = sum(len((chunk.content or "").strip()) for chunk in chunks)
            ctx.info(
                f"Retrieved {len(chunks)} chunks ({total_chars:,} characters)",
                tool_name=TOOL_NAME,
                payload={"chunks": len(chunks), "characters": total_chars},
            )
            ctx.report_progress(100, 100, tool_name=TOOL_NAME)

            lines: list[str] = []
            for index, chunk in enumerate(chunks, 1):
                metadata = chunk.metadata or {}
                section_title = metadata.get("section_title") or metadata.get("section") or "workspace"
                lines.append(f"[{index}] ({section_title})\n{chunk.content.strip()}")
            return "\n\n".join(lines)

        return StructuredTool.from_function(
            func=_retrieve,
            name="retrieve_workspace_context",
            description=(
                "Retrieve authoritative facts about the current workspace "
                "(name, mission, story, sector, categories, team size, "
                "operations, etc.) by semantic search over its indexed "
                "snapshot. Input: a short natural-language query like "
                "'mission and story' or 'team size'. Output: ranked "
                "snippets from the workspace, or an explicit 'no indexed "
                "context' message. ALWAYS call this before answering any "
                "factual question about the workspace — do not guess."
            ),
        )

    def _create_agent_executor(self):
        """Build the LangChain 1.x tool-calling agent graph (``create_agent``).

        Replaces the 0.3 ``AgentExecutor`` + ``create_react_agent`` /
        ``create_tool_calling_agent`` construction. ``create_agent`` is a
        native tool-calling graph — it has no ReAct ``Thought/Action/
        Observation`` prose format, so the whole class of parse-error
        scaffolding the old path carried (``handle_parsing_errors``,
        ``early_stopping_method="force"``, the ``return_stopped_response``
        monkeypatch, the ReAct fallback) is gone.

        Migration notes (docs/plans/LANGCHAIN_1X_MIGRATION_2026-07-18.md):
          - ``self.llm`` is a ``BaseChatModel`` instance; ``create_agent``
            accepts it directly for ``model=`` so the provider port
            abstraction is preserved (no ``"provider:model"`` string).
          - Tools are the same ``StructuredTool`` / ``Tool`` instances the
            decorator framework promotes — tool NAMES are byte-stable, so
            ``Agent.config.custom_profile.tool_whitelist`` still resolves.
          - Memory: the 0.3 ``ConversationBufferMemory`` + conversation-id
            monkeypatches are replaced by SQL-history threading — the handle
            prepends ``self.memory.load_messages()`` (the durable
            Conversation/ConversationMessage window) to every graph invoke,
            and ``memory_service.record_execution`` keeps persisting the new
            turn. One store, no process-local checkpointer fork.
          - The graph is stored on ``self._graph_agent``; ``self.agent_executor``
            is kept as the invocation handle so the ``AgentTestCase`` seam
            (which installs a scripted stub on ``self.agent_executor``) and
            the ``.callbacks`` flush loop in ``execute()`` keep working.
        """
        if not self.tools:
            raise ValueError("No tools defined for agent")

        self._agent_impl = "create_agent"

        callbacks = []
        try:
            if self._telemetry_callback_factory is not None:
                self.telemetry_handler = self._telemetry_callback_factory(agent_id=self.agent_id)
            else:
                # Lazy fallback — import only when no factory was injected
                from components.agents.infrastructure.adapters.langchain.callbacks.telemetry import TelemetryCallback

                self.telemetry_handler = TelemetryCallback(agent_id=self.agent_id)
            callbacks.append(self.telemetry_handler)
        except Exception:
            logger.exception("Failed to initialise telemetry callback for agent %s", self.agent_id)
            self.telemetry_handler = None

        # Add tracing callback via port (vendor-agnostic)
        try:
            session_id = None
            try:
                session_id = self.memory_service.get_conversation_id()
            except Exception:
                logger.debug("Could not resolve conversation_id for tracing session")

            tracing_callback = self._tracing_port.get_langchain_callback(
                agent_id=self.agent_id,
                user_id=str(self.user_id),
                session_id=session_id,
            )
            if tracing_callback is not None:
                callbacks.append(tracing_callback)
                # Also attach to the LLM if it supports callbacks
                if hasattr(self.llm, "callbacks"):
                    if self.llm.callbacks is None:
                        self.llm.callbacks = [tracing_callback]
                    elif tracing_callback not in self.llm.callbacks:
                        self.llm.callbacks.append(tracing_callback)
                logger.info(
                    "Tracing callback attached for agent %s (session_id=%s)",
                    self.agent_id,
                    session_id,
                )
        except Exception:
            logger.exception("Failed to attach tracing callback for agent %s", self.agent_id)

        # Runtime guardrails. In 1.x these are expressed as middleware
        # (a step-cap middleware) rather than AgentExecutor kwargs. The
        # values are parsed here and bound to the recursion limit at
        # invoke time (see ``_invoke_agent_executor``). max_execution_time
        # has no direct create_agent equivalent — it moves to an invoke
        # timeout guard (Phase 5); parsed here so config stays honoured.
        try:
            configured_max_iterations = int(self.config.get("max_iterations", 25))
        except (TypeError, ValueError):
            configured_max_iterations = 25
        try:
            max_tool_calls = int(self.config.get("max_tool_calls", 40))
        except (TypeError, ValueError):
            max_tool_calls = 40
        try:
            max_execution_time_seconds = int(self.config.get("max_execution_time_seconds", 90))
        except (TypeError, ValueError):
            max_execution_time_seconds = 90

        configured_max_iterations = max(configured_max_iterations, 1)
        max_tool_calls = max(max_tool_calls, 1)
        max_execution_time_seconds = max(max_execution_time_seconds, 5)
        # Each tool call is one model turn + one tool turn in the graph, so
        # the LangGraph recursion limit must be ~2× the tool-call budget
        # (plus a small margin for the final answer turn).
        self._max_tool_calls = min(configured_max_iterations, max_tool_calls)
        self._graph_recursion_limit = (self._max_tool_calls * 2) + 2
        self._max_execution_time_seconds = max_execution_time_seconds
        self._run_callbacks = callbacks

        # No checkpointer: conversation continuity is SQL-backed. The durable
        # store is the Conversation/ConversationMessage tables (written by
        # ``memory_service.record_execution`` in ``execute()``); prior turns
        # are threaded into the graph input by the handle's
        # ``history_provider`` (``self.memory.load_messages()``). A process-
        # local InMemorySaver here would fork the conversation per worker AND
        # double-append turns already loaded from SQL.
        self._graph_agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=self._build_system_message(),
            middleware=self._build_agent_middleware(),
        )
        # Keep ``self.agent_executor`` as the invocation handle. It carries
        # the run callbacks so the ``execute()`` flush loop still finds
        # them, and ``AgentTestCase`` overwrites it with a scripted stub.
        self.agent_executor = _GraphExecutorHandle(
            graph=self._graph_agent,
            callbacks=callbacks,
            recursion_limit=self._graph_recursion_limit,
            history_provider=self._load_history_messages,
            rubric_provider=self._resolve_active_rubric,
        )

    def _build_agent_middleware(self) -> list:
        """Middleware for ``create_agent`` (LangChain 1.x cross-cutting hooks).

        Empty by default. ``deepagents.RubricMiddleware`` is attached for
        critic-enabled worker types when the global setting
        ``DEEP_RUBRIC_MIDDLEWARE_ENABLED`` or the agent config opts in — see
        ``components.agents.infrastructure.adapters.langchain.deep.rubric``.
        The hand-rolled ``deep/critic.py`` loop remains the fallback while the
        flag is off.
        """
        middleware: list = []
        self._rubric_middleware_attached = False
        rubric_cfg = self.config.get("rubric_middleware")
        if not rubric_cfg:
            try:
                from components.agents.infrastructure.adapters.langchain.deep.rubric import (
                    rubric_middleware_enabled,
                )

                rubric_cfg = rubric_middleware_enabled(self.config)
            except Exception:
                rubric_cfg = False
        if rubric_cfg:
            try:
                from components.agents.infrastructure.adapters.langchain.deep.rubric import (
                    build_rubric_middleware,
                )

                mw = build_rubric_middleware(
                    agent=self,
                    config=rubric_cfg if isinstance(rubric_cfg, dict) else {},
                )
                if mw is not None:
                    middleware.append(mw)
                    self._rubric_middleware_attached = True
            except Exception:
                # The rubric loop is a quality enhancement, never a gate that
                # can block agent construction — degrade to no middleware.
                logger.exception("rubric middleware unavailable for agent %s; continuing without", self.agent_id)
        return middleware

    def _resolve_active_rubric(self) -> str | None:
        """The rubric to place on the invocation state, or ``None``.

        deepagents' ``RubricMiddleware`` is state-activated: it only grades
        when ``state["rubric"]`` is set. Only agents that actually carry the
        middleware get a rubric on their invokes.
        """
        if not getattr(self, "_rubric_middleware_attached", False):
            return None
        try:
            from components.agents.infrastructure.adapters.langchain.deep.rubric import (
                resolve_rubric_text,
            )

            return resolve_rubric_text(self)
        except Exception:
            return None

    def _drain_rubric_evaluations(self) -> dict | None:
        """Pop the rubric grader's evaluations for the invoke that just ran.

        The middleware's ``on_evaluation`` callback fills a per-agent
        collector (``deep/rubric.py``) because deepagents 0.6.12 keeps the
        evaluations in private state stripped from the graph output. Returns
        the collector payload or ``None``; never raises — rubric telemetry
        is an enhancement, not a gate.
        """
        if not getattr(self, "_rubric_middleware_attached", False):
            return None
        try:
            from components.agents.infrastructure.adapters.langchain.deep.rubric import (
                drain_rubric_evaluations,
            )

            return drain_rubric_evaluations(self)
        except Exception:
            logger.warning("rubric evaluation drain failed for agent %s", self.agent_id, exc_info=True)
            return None

    def _load_history_messages(self) -> list:
        """Prior conversation turns for the graph input (SQL-backed window).

        Replaces the 0.3 ``ConversationBufferMemory`` injection AND the two
        conversation-id monkeypatches (``_patch_memory_conversation_id`` /
        ``_patch_langchain_memory``): the memory object is now a plain
        SQL-window loader whose conversation_id is authoritative because it
        is constructed FROM ``memory_service.get_conversation_id()`` — there
        is no LangChain-internal save path left to drift it.
        """
        memory = getattr(self, "memory", None)
        if memory is None:
            return []
        loader = getattr(memory, "load_messages", None)
        if callable(loader):
            return loader()
        # Duck-typed fallback: anything exposing chat-history messages.
        chat_memory = getattr(memory, "chat_memory", None)
        messages = getattr(chat_memory, "messages", None)
        return list(messages) if messages else []

    def _apply_run_context(self, run_context: dict[str, Any]) -> None:
        """Override conversation_id for run-scoped sub-agent execution."""
        conversation_id = run_context.get("conversation_id")
        if not conversation_id:
            return
        try:
            from django.db import transaction

            from infrastructure.persistence.ai.conversations.models import Conversation

            # Idempotent create wrapped in a savepoint. Two run-scoped sub-agent
            # instances can share one conversation_id and both pass the
            # existence check before either commits; the loser hits a duplicate
            # pkey. Without the savepoint that caught IntegrityError poisons the
            # OUTER transaction (Postgres aborts it), and every later query in
            # the run then fails with "current transaction is aborted" — which
            # is what surfaced the run-level IntegrityError. get_or_create +
            # atomic() makes the collision a true no-op.
            with transaction.atomic():
                Conversation.objects.get_or_create(
                    id=conversation_id,
                    defaults={
                        "user_id": self.user_id,
                        "title": f"{self.__class__.__name__} Run Context",
                        "metadata": {
                            "agent_id": str(self.agent_id),
                            "agent_type": self.__class__.__name__,
                            "workspace_id": str(self.workspace_id),
                            "run_id": run_context.get("run_id"),
                            "plan_id": run_context.get("plan_id"),
                            # Internal orchestration artifact — not a
                            # user-facing chat thread. The list endpoint
                            # filters these out so the UI sees only the
                            # conversations ``AgentChatUseCase`` created.
                            "internal": True,
                        },
                    },
                )
        except Exception:
            logger.warning("Failed to ensure run conversation for agent %s", self.agent_id, exc_info=True)

        self._override_conversation_id = conversation_id
        if hasattr(self.memory, "chat_memory") and hasattr(self.memory.chat_memory, "conversation_id"):
            self.memory.chat_memory.conversation_id = conversation_id
        if hasattr(self.agent_executor, "memory") and hasattr(self.agent_executor.memory, "chat_memory"):
            if hasattr(self.agent_executor.memory.chat_memory, "conversation_id"):
                self.agent_executor.memory.chat_memory.conversation_id = conversation_id

        limits = run_context.get("memory_limits") if isinstance(run_context, dict) else None
        if limits and hasattr(self.memory, "chat_memory"):
            for attr in ("max_messages", "max_message_chars", "max_total_chars"):
                if attr in limits and hasattr(self.memory.chat_memory, attr):
                    setattr(self.memory.chat_memory, attr, limits.get(attr))

    def _apply_tool_policy(self, run_context: dict[str, Any] | None) -> list[BaseTool] | None:
        """Restrict tools per run_context; returns original tools if modified."""
        if not run_context:
            return None
        allowed = run_context.get("allowed_tools") if isinstance(run_context, dict) else None
        blocked = run_context.get("blocked_tools") if isinstance(run_context, dict) else None
        if not allowed and not blocked:
            return None

        base_tools = self._all_tools or self.tools
        filtered = []
        for tool in base_tools:
            if allowed and tool.name not in allowed:
                continue
            if blocked and tool.name in blocked:
                continue
            filtered.append(tool)

        if filtered == self.tools:
            return None

        original = list(self.tools)
        self.tools = filtered
        self._create_agent_executor()
        return original

    def _restore_tool_policy(self, original_tools: list[BaseTool] | None) -> None:
        if not original_tools:
            return
        self.tools = list(original_tools)
        self._create_agent_executor()

    def _apply_custom_profile_tool_whitelist(self, run_context: dict[str, Any]) -> None:
        """
        Apply per-agent tool whitelist as the tightest tool restriction.

        Behavior:
        - If `run_context["allowed_tools"]` is already set, intersect with `tool_whitelist`.
        - If no `run_context["allowed_tools"]` is set, use `tool_whitelist` directly.
        - If the whitelist contains no valid tool names for this agent, ignore it (so we don't
          accidentally leave the agent with zero tools and a broken ReAct format).
        """
        custom_profile = self.config.get("custom_profile")
        if not isinstance(custom_profile, dict):
            return
        raw_whitelist = custom_profile.get("tool_whitelist") or []
        if isinstance(raw_whitelist, str):
            raw_whitelist = [raw_whitelist]
        if not isinstance(raw_whitelist, list):
            return

        requested = [str(name or "").strip() for name in raw_whitelist]
        requested = [name for name in requested if name]
        if not requested:
            return

        available_tools = self._all_tools or self.tools
        available_names = {tool.name for tool in available_tools}
        whitelist = [name for name in requested if name in available_names]
        if not whitelist:
            logger.warning(
                "Agent %s tool_whitelist contained no valid tool names; ignoring. requested=%s available=%s",
                self.agent_id,
                requested,
                sorted(available_names),
            )
            return

        existing_allowed = run_context.get("allowed_tools")
        if isinstance(existing_allowed, str):
            existing_allowed = [existing_allowed]
        if isinstance(existing_allowed, list):
            allowed_set = {str(name or "").strip() for name in existing_allowed if str(name or "").strip()}
            allowed = [name for name in whitelist if name in allowed_set]
        else:
            allowed = list(whitelist)

        if not allowed:
            logger.warning(
                "Agent %s tool_whitelist would restrict allowed_tools to empty; ignoring. whitelist=%s allowed_tools=%s",
                self.agent_id,
                whitelist,
                existing_allowed,
            )
            return

        run_context["allowed_tools"] = allowed

    def _build_system_message(self) -> str:
        """Compose the system message shared by both prompt flavours.

        Keeps the profile blurb + persona/tone/output-format in one
        place so the ReAct and tool-calling paths stay in sync.
        """
        profile = self._get_agent_profile()
        profile_name = profile.get("name") or self.__class__.__name__.replace("Agent", " Agent")
        profile_summary = profile.get("summary") or ""
        capabilities = profile.get("capabilities") or []

        capabilities_section = ""
        if capabilities:
            joined = "\n".join(f"- {item}" for item in capabilities)
            capabilities_section = f"\n\nYour core capabilities include:\n{joined}"

        summary_section = f"\n{profile_summary}" if profile_summary else ""

        customization = self._get_prompt_customization_vars()
        persona = customization.get("persona", "").strip()
        tone = customization.get("tone", "").strip()
        output_format = customization.get("output_format", "").strip()
        default_report_period = customization.get("default_report_period", "").strip()

        custom_lines = []
        if persona:
            custom_lines.append(f"Persona: {persona}")
        if tone:
            custom_lines.append(f"Tone: {tone}")
        if output_format:
            custom_lines.append(f"Output format: {output_format}")
        if default_report_period:
            custom_lines.append(f"Default report period: {default_report_period}")
        custom_block = ("\n\n" + "\n".join(custom_lines)) if custom_lines else ""

        guidelines = (
            "\n\nGuidelines:\n"
            "- Call `retrieve_workspace_context` when the question needs "
            "workspace identity, mission, story, sector, categories, tags, "
            "operations, or owner-curated narrative context — that is what "
            "the retrieval surface actually indexes today. For specific data "
            "(recipient names, donor lists, transactions, budgets, grants, "
            "campaigns, projects, audit history) call your domain tools "
            "directly; the retrieval surface does not index that data today. "
            "See `docs/plans/RAG_AUDIT_AND_ROADMAP.md` Tier 2 for the plan "
            "to make the snapshot data-aware.\n"
            "- Answer from whatever the tools return. The workspace snapshot "
            "contains identity, mission, classification, operations, and "
            "team/follower counts — enough for a TLDR or overview, but "
            "names of donors, recipients, grants, or transactions are not "
            "in there. Craft a 2-3 sentence summary from whatever metadata "
            "you have.\n"
            '- NEVER say "there is not enough information", "the workspace '
            'doesn\'t specify", "details are not available", or similar '
            "phrases. If the workspace has no narrative content, just say so "
            'plainly ("No mission description has been added yet — the '
            'workspace has N teams and M members.") and still answer from '
            "the metadata you have.\n"
            "- If `retrieve_workspace_context` returns empty, call a workspace "
            "tool like `get_workspace_info` or `get_organization_info` (no "
            "arguments needed — defaults to the active workspace) before "
            "deflecting.\n"
            "- Prefer detailed, grounded responses that surface the actual tool "
            "output (bullet lists, line breaks) rather than paraphrasing.\n"
            '- When the user asks for a plan, report, or "full" details, '
            "paste the structured tool output directly in the final answer.\n"
            '- If a tool returns zero items, say so explicitly ("There are 0 '
            "tasks in this workspace\") — don't deflect."
        )

        return (
            f"You are the {profile_name} working for workspace {self.workspace_id}."
            f"{summary_section}{capabilities_section}{custom_block}{guidelines}"
        )

    # NOTE (LangChain 1.x migration, 2026-07-18): ``_create_chat_prompt_template``
    # and the legacy ReAct ``_create_prompt_template`` were DELETED. ``create_agent``
    # takes the system prompt as a plain ``system_prompt=`` string
    # (``_build_system_message()``) and manages the message list itself — there is
    # no ``{input}`` / ``agent_scratchpad`` placeholder template, and no ReAct prose
    # format (hence no fallback template). See ``_create_agent_executor``.

    def _get_prompt_customization_vars(self) -> dict[str, str]:
        """
        Return prompt variables that customize the agent behavior.

        These values are persisted via `PATCH /ai/agents/{agent_id}/settings/` under
        `Agent.config["custom_profile"]` and mirrored to the runtime agent instance as `self.config`.
        """
        custom_profile = self.config.get("custom_profile")
        if not isinstance(custom_profile, dict):
            custom_profile = {}
        return {
            "persona": str(custom_profile.get("persona") or "").strip(),
            "tone": str(custom_profile.get("tone") or "").strip(),
            "output_format": str(custom_profile.get("output_format") or "").strip(),
            "default_report_period": str(custom_profile.get("default_report_period") or "").strip(),
        }

    def _build_graph_executor(self, callbacks: list | None = None) -> None:
        """Build a LangGraph StateGraph executor as an alternative to AgentExecutor.

        Opt in via ``config["use_langgraph"] = True``.
        """
        if not self._use_langgraph:
            return

        profile = self._get_agent_profile()
        profile_name = profile.get("name") or self.__class__.__name__
        system_prompt = (
            f"You are the {profile_name} working for workspace {self.workspace_id}. {profile.get('summary', '')}"
        )

        # Inject session memory context if available
        session_ctx = self.config.get("session_memory_context", "")
        if session_ctx:
            system_prompt += f"\n\n{session_ctx}"

        self.graph_executor = build_graph_executor(
            llm=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            max_iterations=int(self.config.get("max_iterations", 15)),
            callbacks=callbacks,
        )
        if self.graph_executor:
            logger.info("LangGraph executor built for agent %s", self.agent_id)

    def _invoke_graph_executor(self, query: str) -> dict[str, Any]:
        """Invoke the LangGraph executor and return a result dict compatible with AgentExecutor."""
        if not self.graph_executor:
            raise ValueError("Graph executor is not initialised")

        result = self.graph_executor.invoke(
            {
                "messages": [HumanMessage(content=query)],
                "iteration_count": 0,
            }
        )

        answer = result.get("final_answer", "")
        error = result.get("error")

        if error:
            return {"output": f"Error: {error}"}
        return {"output": answer}

    def _invoke_agent_executor(
        self,
        inputs: dict[str, Any],
        *,
        retries: int | None = None,
    ) -> dict[str, Any]:
        """Invoke the agent executor with automatic retries for transient LLM failures."""
        # Use LangGraph if available and enabled
        if self._use_langgraph and self.graph_executor:
            query = inputs.get("input", "")
            return self._invoke_graph_executor(query)

        if not self.agent_executor:
            raise ValueError("Agent executor is not initialised")

        retry_budget = self.config.get("llm_retry_attempts", 1) if retries is None else retries
        try:
            retry_budget = int(retry_budget)
        except (TypeError, ValueError):
            retry_budget = 1
        retry_budget = max(retry_budget, 0)

        # Guardrail: bound prompt/input size to avoid runaway latency/cost.
        try:
            max_input_chars = int(self.config.get("max_input_chars", 12000))
        except (TypeError, ValueError):
            max_input_chars = 12000
        max_input_chars = max(max_input_chars, 500)
        input_preview = inputs.get("input", "") if isinstance(inputs, dict) else ""
        if isinstance(input_preview, str) and len(input_preview) > max_input_chars:
            raise ValueError(f"Agent input exceeds max_input_chars ({len(input_preview)} > {max_input_chars})")

        # Log before invoking to track LLM calls
        logger.info(
            "Agent %s invoking executor with input: %s",
            self.agent_id,
            inputs.get("input", "")[:100] if inputs.get("input") else str(inputs)[:100],
        )
        if hasattr(self.agent_executor, "callbacks") and self.agent_executor.callbacks:
            callback_types = [type(cb).__name__ for cb in self.agent_executor.callbacks]
            logger.info(
                "Agent %s executor has %d callbacks: %s",
                self.agent_id,
                len(self.agent_executor.callbacks),
                callback_types,
            )

        if not RETRYABLE_AGENT_EXCEPTIONS or retry_budget == 0:
            result = self.agent_executor.invoke(inputs)
            logger.info("Agent %s executor completed (no retries)", self.agent_id)
            return result

        attempt = 0
        while True:
            try:
                result = self.agent_executor.invoke(inputs)
                logger.info("Agent %s executor completed on attempt %d", self.agent_id, attempt + 1)
                return result
            except RETRYABLE_AGENT_EXCEPTIONS as exc:  # pragma: no cover - depends on external API behaviour
                if attempt >= retry_budget:
                    raise
                attempt += 1
                import time  # local import keeps optional dependency scoped

                wait_seconds = min(2**attempt, 5)
                logger.warning(
                    "Agent %s LLM invocation failed with %s (attempt %s/%s); retrying in %ss",
                    self.agent_id,
                    exc.__class__.__name__,
                    attempt,
                    retry_budget + 1,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

    def _is_retryable_agent_error(self, exc: BaseException) -> bool:
        return bool(RETRYABLE_AGENT_EXCEPTIONS) and isinstance(exc, RETRYABLE_AGENT_EXCEPTIONS)

    def execute(
        self,
        query: str,
        *,
        execution: Any = None,
        execution_id: int = None,
        task_id: str = None,
        performed_by: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute the agent with a given query

        Args:
            query: The user's request

        Returns:
            Dictionary containing the result and metadata
        """
        # Early input validation — before any memory/state work
        try:
            max_query_len = int(self.config.get("max_input_chars", 12000))
        except (TypeError, ValueError):
            max_query_len = 12000
        if query and len(query) > max(max_query_len, 500):
            return {
                "success": False,
                "error": f"Query too long ({len(query)} chars, max {max_query_len})",
                "agent_id": self.agent_id,
            }

        logger.info("Agent %s execution started with query: %s", self.agent_id, query[:100] if query else "")
        tool_restore: list[BaseTool] | None = None
        run_context = None
        # Stash the active DeepRunContext (if the deep runner injected
        # one) on self for the duration of this execute() call. Tool
        # closures (e.g. _retrieve in _build_workspace_retrieval_tool)
        # read it via ``self._active_deep_run_context`` and emit
        # narrative log + progress lines mid-execution. Restored to
        # None in finally so the same agent serving a follow-on call
        # without a context doesn't leak the previous run's emit hook.
        previous_deep_run_context = getattr(self, "_active_deep_run_context", None)
        if context and isinstance(context, dict):
            self._active_deep_run_context = context.get("deep_run_context")
        else:
            self._active_deep_run_context = None
        # Reset the artifact collector for this turn so a previous call's
        # PDF doesn't bleed into the next assistant message. Tools call
        # ``self.collect_artifact(...)`` during execution; we harvest below.
        self._pending_artifacts = []
        try:
            requested_run_context = None
            if context and isinstance(context, dict):
                requested_run_context = context.get("run_context")

            custom_profile = self.config.get("custom_profile")
            has_tool_whitelist = bool(isinstance(custom_profile, dict) and custom_profile.get("tool_whitelist"))

            if isinstance(requested_run_context, dict) or has_tool_whitelist:
                run_context = dict(requested_run_context or {})
                if has_tool_whitelist:
                    self._apply_custom_profile_tool_whitelist(run_context)
                self._apply_run_context(run_context)
                tool_restore = self._apply_tool_policy(run_context)
            import time

            start_time = time.time()

            self.state.status = "running"
            self.state.updated_at = datetime.now()
            if self.telemetry_handler:
                self.telemetry_handler.reset()

            meta_result = self._maybe_handle_meta_query(query)
            if meta_result is not None:
                execution_time_ms = int((time.time() - start_time) * 1000)
                execution = self.memory_service.record_execution(
                    query=query,
                    result=meta_result,
                    success=True,
                    execution_time_ms=execution_time_ms,
                    execution=execution,
                    execution_id=execution_id,
                    status=EXECUTION_STATUS_COMPLETED,
                    progress=100,
                    state=self._execution_state_with_telemetry(),
                    task_id=task_id,
                    add_user_message=execution is None and execution_id is None,
                )

                self.state.results.append(
                    {
                        "query": query,
                        "result": meta_result,
                        "timestamp": datetime.now().isoformat(),
                        "execution_id": str(execution.id),
                    }
                )
                self.state.status = "completed"
                self.state.updated_at = datetime.now()

                self._maybe_log_auto_action(
                    performed_by=performed_by,
                    query=query,
                    result_text=meta_result,
                    context=self._merge_session_context(context, execution),
                )

                result_payload = {
                    "success": True,
                    "result": meta_result,
                    "execution_id": str(execution.id),
                    "execution_time_ms": execution_time_ms,
                    "agent_id": self.agent_id,
                    "state": self.state.to_dict(),
                }
                self._maybe_log_run_telemetry(run_context, success=True)
                return result_payload

            logger.info(f"Agent {self.agent_id} executing query: {query}")

            # Update Langfuse callback session_id before execution to ensure traces are grouped correctly
            if self.agent_executor and hasattr(self.agent_executor, "callbacks") and self.agent_executor.callbacks:
                try:
                    current_conversation_id = self.memory_service.get_conversation_id()
                    for callback in self.agent_executor.callbacks:
                        # Check if this is a Langfuse callback and update session_id
                        if hasattr(callback, "session_id"):
                            if callback.session_id != current_conversation_id:
                                callback.session_id = current_conversation_id
                                logger.debug(
                                    "Updated Langfuse callback session_id to %s for agent %s",
                                    current_conversation_id,
                                    self.agent_id,
                                )
                except Exception as e:
                    logger.debug("Could not update callback session_id: %s", e)

            # Rubric telemetry: discard any evaluations left over from a
            # prior aborted invoke so this turn's grading attributes only
            # to this turn (the collector is per-agent, agents are cached).
            self._drain_rubric_evaluations()

            # Execute the agent. The ``{"input": query}`` contract is kept
            # for the scripted ``AgentTestCase`` stub AND the real 1.x path:
            # ``_GraphExecutorHandle.invoke`` translates it to a
            # ``{"messages": [...]}`` graph state and back (customization is
            # baked into the create_agent ``system_prompt`` at build time).
            result = self._invoke_agent_executor({"input": query})

            # Pop this invoke's grader evaluations (delivered via the
            # middleware's ``on_evaluation`` callback — deepagents keeps them
            # in private state stripped from the graph output) so they ride
            # the response to the deep-run worker, which owns the task_id
            # needed to stamp ``run_metadata["rubric_verdicts"]``.
            rubric_evaluations = self._drain_rubric_evaluations()

            # Persist tool observations to DeepRunLog so the eval harness
            # and the realtime chat UI can see which tools the agent ran
            # with what arguments and what they returned. Only fires inside
            # a deep-run (run_context is set with a thread_id); standalone
            # execute() calls have no DeepRun to write against and skip
            # this path. The persist call itself is fault-isolated so the
            # chat reply never depends on observability succeeding.
            try:
                self._persist_tool_observations(run_context, result.get("intermediate_steps"))
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "tool-observation persist failed for agent %s",
                    self.agent_id,
                    exc_info=True,
                )

            # Flush Langfuse callbacks to ensure traces are sent
            if self.agent_executor and hasattr(self.agent_executor, "callbacks") and self.agent_executor.callbacks:
                for callback in self.agent_executor.callbacks:
                    if hasattr(callback, "flush"):
                        try:
                            callback.flush()
                            logger.debug("Flushed Langfuse callback for agent %s", self.agent_id)
                        except Exception as e:
                            logger.warning("Failed to flush Langfuse callback: %s", e)

            execution_time_ms = int((time.time() - start_time) * 1000)
            result_text = result.get("output", "")

            # Snapshot any artifacts tools collected during this turn so
            # they ride out on the assistant message's metadata. Read
            # before clearing to keep the collector clean for follow-on
            # calls without contaminating this one.
            collected_artifacts = list(self._pending_artifacts)

            # Record execution in memory service
            execution = self.memory_service.record_execution(
                query=query,
                result=result_text,
                success=True,
                execution_time_ms=execution_time_ms,
                execution=execution,
                execution_id=execution_id,
                status=EXECUTION_STATUS_COMPLETED,
                progress=100,
                state=self._execution_state_with_telemetry(),
                task_id=task_id,
                add_user_message=execution is None and execution_id is None,
                artifacts=collected_artifacts or None,
            )

            # Update state
            self.state.results.append(
                {
                    "query": query,
                    "result": result_text,
                    "timestamp": datetime.now().isoformat(),
                    "execution_id": str(execution.id),
                }
            )
            self.state.status = "completed"
            self.state.updated_at = datetime.now()

            self._maybe_log_auto_action(
                performed_by=performed_by,
                query=query,
                result_text=result_text,
                context=self._merge_session_context(context, execution),
            )

            result_payload = {
                "success": True,
                "result": result_text,
                "execution_id": str(execution.id),
                "execution_time_ms": execution_time_ms,
                "agent_id": self.agent_id,
                "state": self.state.to_dict(),
            }
            if rubric_evaluations:
                result_payload["rubric_evaluations"] = rubric_evaluations
            self._maybe_log_run_telemetry(run_context, success=True)
            return result_payload

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)

            logger.exception("Agent %s execution failed", self.agent_id)

            self.state.errors.append(error_msg)
            self.state.status = "failed"
            self.state.updated_at = datetime.now()

            execution = self.memory_service.record_execution(
                query=query,
                result="",
                success=False,
                error_message=error_msg,
                execution_time_ms=execution_time_ms,
                execution=execution,
                execution_id=execution_id,
                status=EXECUTION_STATUS_FAILED,
                progress=100,
                state=self._execution_state_with_telemetry(),
                task_id=task_id,
                add_user_message=execution is None and execution_id is None,
                add_agent_message=True,
            )

            result_payload = {
                "success": False,
                "error": error_msg,
                "execution_id": str(execution.id),
                "execution_time_ms": execution_time_ms,
                "agent_id": self.agent_id,
                "state": self.state.to_dict(),
            }
            self._maybe_log_run_telemetry(run_context, success=False, error=error_msg)
            return result_payload
        finally:
            if tool_restore:
                self._restore_tool_policy(tool_restore)
            # Restore the DeepRunContext slot to whatever it held before
            # this call so re-entrant or back-to-back execute() calls
            # don't leak each other's emit hooks. The agent itself is
            # cached across calls.
            self._active_deep_run_context = previous_deep_run_context

    def _maybe_log_auto_action(
        self,
        *,
        performed_by: str | None,
        query: str,
        result_text: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        # Phase 5 of the Agents-as-Teammates migration removed the AIAction
        # row that used to back this audit trail. The teammate-attribution
        # check + log line stay so SRE has greppable per-agent telemetry;
        # nothing writes to the deleted AIAction table.
        if not performed_by or not self.workspace_id:
            return

        try:
            from components.agents.infrastructure.services.actions_service import get_ai_action_service

            action_service = get_ai_action_service()
            teammate = action_service.get_teammate(self.workspace_id)
            if not teammate or str(teammate.user_id) != str(performed_by):
                return

            summary = result_text.strip() if result_text else "Execution completed with no textual result."

            logger.info(
                "agent_auto_run agent=%s workspace_id=%s action_type=%s summary=%s",
                self.__class__.__name__,
                self.workspace_id,
                f"{self.__class__.__name__}.auto_run",
                self._truncate(summary),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Unable to log auto action for agent %s: %s", self.agent_id, exc)

    @staticmethod
    def _truncate(text: str, length: int = 500) -> str:
        if len(text) <= length:
            return text
        return f"{text[: length - 3]}..."

    @staticmethod
    def _merge_session_context(base_context: dict[str, Any] | None, execution: Any = None) -> dict[str, Any]:
        merged = dict(base_context or {})
        if execution and getattr(execution, "id", None):
            merged.setdefault("session_id", str(execution.id))
        return merged

    def pause(self):
        """Pause the agent execution"""
        self.state.status = "paused"
        self.state.updated_at = datetime.now()

    def resume(self):
        """Resume the agent execution"""
        self.state.status = "running"
        self.state.updated_at = datetime.now()

    def get_state(self) -> dict[str, Any]:
        """Get current agent state"""
        return self.state.to_dict()

    def get_memory_stats(self) -> dict[str, Any]:
        """Get memory statistics for this agent"""
        return self.memory_service.get_memory_stats()

    def get_conversation_history(
        self,
        limit: int | None = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[dict[str, Any]]:
        """Get conversation history for this agent with pagination support."""
        return self.memory_service.get_conversation_history(
            limit=limit,
            offset=offset,
            order=order,
        )

    def clear_memory(self) -> None:
        """Clear all memory for this agent"""
        self.memory_service.clear_memory()
        logger.info(f"Cleared memory for agent {self.agent_id}")

    def add_system_message(self, content: str) -> None:
        """Add system message to agent memory"""
        self.memory_service.add_system_message(content)
        logger.info(f"Added system message to agent {self.agent_id}")

    def add_context(self, key: str, value: Any):
        """Add context to the agent state"""
        self.state.context[key] = value
        self.state.updated_at = datetime.now()

    def get_context(self, key: str) -> Any:
        """Get context from the agent state"""
        return self.state.context.get(key)

    def _get_agent_profile(self) -> dict[str, Any]:
        # Class-level profile (ADR 0003) is the default. The DB row's
        # `config["profile"]` overrides any field on a per-workspace
        # basis. Falls back to the class docstring + class name when
        # neither is set so legacy agents without a `profile` attribute
        # still produce something useful.
        class_profile = dict(getattr(type(self), "profile", {}) or {})
        profile_cfg = self.config.get("profile") or {}
        summary_fallback = self.config.get("description") or (self.__doc__ or "").strip()
        profile = {
            "name": (
                profile_cfg.get("name")
                or class_profile.get("name")
                or self.__class__.__name__.replace("Agent", " Agent")
            ),
            "summary": (profile_cfg.get("summary") or class_profile.get("summary") or summary_fallback),
            "capabilities": (profile_cfg.get("capabilities") or class_profile.get("capabilities") or []),
            "sample_prompts": (
                profile_cfg.get("sample_prompts")
                or profile_cfg.get("examples")
                or class_profile.get("sample_prompts")
                or class_profile.get("examples")
                or []
            ),
        }
        notes = profile_cfg.get("notes") or class_profile.get("notes")
        if notes:
            profile["notes"] = notes
        return profile

    def _maybe_handle_meta_query(self, query: str) -> str | None:
        if not query:
            return None
        lowered = query.strip().lower()
        triggers = [
            "what is this agent",
            "who are you",
            "what can you do",
            "help me understand",
            "what are you",
            "how can you help",
            "what is your purpose",
            "what do you do",
            "tell me what you do",
            "tell me what you can do",
            "tell me about yourself",
            "what should i ask you",
            "what can i ask you",
            "what are your capabilities",
        ]
        if not any(trigger in lowered for trigger in triggers):
            return None

        profile = self._get_agent_profile()
        lines: list[str] = []
        title = profile.get("name") or self.__class__.__name__
        lines.append(f"{title} Overview")

        summary = profile.get("summary")
        if summary:
            lines.append("")
            lines.append(summary)

        capabilities = profile.get("capabilities") or []
        if capabilities:
            lines.append("")
            lines.append("Key capabilities:")
            for capability in capabilities:
                lines.append(f"- {capability}")

        sample_prompts = profile.get("sample_prompts") or []
        if sample_prompts:
            lines.append("")
            lines.append("Try asking:")
            for prompt in sample_prompts:
                lines.append(f"- {prompt}")

        if profile.get("notes"):
            lines.append("")
            lines.append(profile["notes"])

        return "\n".join(lines)

    def _get_telemetry_snapshot(self) -> dict[str, Any] | None:
        if not self.telemetry_handler:
            return None
        try:
            return self.telemetry_handler.summary()
        except Exception:
            logger.debug("Failed to collect telemetry for agent %s", self.agent_id, exc_info=True)
            return None

    def _execution_state_with_telemetry(self) -> dict[str, Any]:
        state = self.state.to_dict()
        telemetry = self._get_telemetry_snapshot()
        if telemetry:
            state["telemetry"] = telemetry
        return state

    # Max characters persisted per (tool_input, tool_output) on a
    # tool_observation log row. 4000 covers ~all realistic agent tool
    # outputs (donor lists, balance snapshots, retrieve_workspace_context
    # bodies are ~800 chars each × 5 chunks) without inviting a 100KB
    # CSV dump from a misbehaving tool to break the JSON column or the
    # websocket envelope. Truncation is recorded via the
    # `truncated_input` / `truncated_output` flags on the payload so the
    # eval harness and chat UI can label trimmed cells.
    _TOOL_OBSERVATION_MAX_CHARS = 4000

    def _persist_tool_observations(
        self,
        run_context: dict[str, Any] | None,
        intermediate_steps: Any | None,
    ) -> None:
        """Log each (action, observation) the ReAct executor produced
        as a ``tool_observation`` DeepRunLog row.

        LangChain's ``AgentExecutor`` with ``return_intermediate_steps=True``
        returns a list of ``(AgentAction, observation)`` pairs alongside
        the final ``output``. The deep-run telemetry summary captures
        *counts* of tool calls (``tools``, ``agent_actions``) but not
        the (input, output) bodies themselves, which is the data the
        RAG eval's Faithfulness metric needs to see to score answers
        whose evidence came from a tool result (e.g.
        ``donation_agent.top_donors`` reads the ORM directly and the
        retrieved workspace-snapshot chunks won't contain those
        donation rows).

        Persisting per-step rows here also makes the frontend chat UI
        able to render which tool ran and with what arguments — the
        existing ``DeepRunLog.post_save`` signal bridge picks the rows
        up and streams them over the per-run WebSocket channel.

        Bounded to ``_TOOL_OBSERVATION_MAX_CHARS`` per field so a CSV
        dump tool can't break the JSON column. Failures are swallowed
        — observability must never crash the run. The caller already
        wraps this in a try/except too, so this is belt-and-braces.
        """
        if not run_context or not isinstance(run_context, dict):
            return
        thread_id = run_context.get("run_id") or run_context.get("plan_id")
        if not thread_id:
            return
        if not intermediate_steps:
            return

        try:
            from components.agents.infrastructure.gateways.deep.logging import (
                log_deep_event,
            )
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "deep logging unavailable; skipping tool observation persist",
                exc_info=True,
            )
            return

        max_chars = self._TOOL_OBSERVATION_MAX_CHARS

        for step in intermediate_steps:
            try:
                action, observation = step[0], step[1]
            except (TypeError, IndexError, KeyError):
                # Future LangChain versions may change the tuple shape;
                # skip anything that doesn't unpack cleanly rather than
                # crash mid-loop.
                continue
            tool_name = getattr(action, "tool", "") or ""
            if not tool_name:
                continue

            raw_input = getattr(action, "tool_input", "")
            if isinstance(raw_input, dict):
                try:
                    raw_input_str = json.dumps(raw_input, default=str)
                except Exception:  # pylint: disable=broad-except
                    raw_input_str = str(raw_input)
            else:
                raw_input_str = "" if raw_input is None else str(raw_input)
            raw_output_str = "" if observation is None else str(observation)

            log_deep_event(
                thread_id,
                "tool_observation",
                agent_type=self.__class__.__name__,
                tool_name=tool_name,
                payload={
                    "tool_input": raw_input_str[:max_chars],
                    "tool_output": raw_output_str[:max_chars],
                    "truncated_input": len(raw_input_str) > max_chars,
                    "truncated_output": len(raw_output_str) > max_chars,
                },
            )

    def _maybe_log_run_telemetry(
        self,
        run_context: dict[str, Any] | None,
        *,
        success: bool,
        error: str | None = None,
    ) -> None:
        if not run_context or not isinstance(run_context, dict):
            return
        run_id = run_context.get("run_id") or run_context.get("plan_id")
        if not run_id:
            return
        telemetry = self._get_telemetry_snapshot()
        if not telemetry and not error:
            return
        try:
            from components.agents.infrastructure.gateways.deep.logging import log_deep_event

            payload = {"telemetry": telemetry} if telemetry else {}
            if error:
                payload["error"] = error
            log_deep_event(
                run_id,
                "run_telemetry",
                status="success" if success else "failed",
                agent_type=self.__class__.__name__,
                payload=payload,
            )
        except Exception:
            logger.debug("Failed to log deep run telemetry for agent %s", self.agent_id, exc_info=True)


class AgentRegistry:
    """Registry for managing available agents"""

    _agents: dict[str, type] = {}

    @classmethod
    def _load_class(cls, dotted_path: str) -> type:
        module_path, class_name = dotted_path.rsplit(".", 1)
        module = import_module(module_path)
        return getattr(module, class_name)

    @classmethod
    def register(cls, name: str, agent_class: Union[type, str]):
        """Register an agent class or import path"""
        if isinstance(agent_class, str):
            agent_class = cls._load_class(agent_class)
        cls._agents[name] = agent_class
        logger.info("Registered agent: %s", name)

    @classmethod
    def get_agent_class(cls, name: str) -> type | None:
        """Get an agent class by name"""
        return cls._agents.get(name)

    @classmethod
    def list_agents(cls) -> list[str]:
        """List all registered agents"""
        return list(cls._agents.keys())

    @classmethod
    def canonical_name_for(cls, slug: str) -> str:
        """Resolve an agent slug or alias to its canonical (registered) name.

        Returns the slug unchanged if it isn't in the registry — keeps
        sentinels like ``clarify`` and unregistered planner outputs
        intact so a downstream consumer can decide how to render them.
        Used by the chat-header resource so the surface always shows
        ``writing_agent`` rather than ``letter_agent`` etc.
        """
        if not slug:
            return ""
        agent_class = cls._agents.get(slug)
        if agent_class is None:
            return slug
        return getattr(agent_class, "_canonical_agent_name", slug)

    @classmethod
    def display_name_for(cls, slug: str) -> str:
        """Resolve a slug or alias to a human-readable label.

        Reads ``profile['name']`` from the registered class when set,
        otherwise titlecases the canonical slug. Fallbacks: if the slug
        isn't in the registry, titlecase the raw slug so even
        sentinels (e.g. ``clarify``) render as ``Clarify``.
        """
        if not slug:
            return ""
        agent_class = cls._agents.get(slug)
        if agent_class is None:
            return slug.replace("_", " ").title()
        profile = getattr(agent_class, "profile", {}) or {}
        explicit = profile.get("name") if isinstance(profile, dict) else None
        if explicit:
            return str(explicit)
        canonical = getattr(agent_class, "_canonical_agent_name", slug)
        return canonical.replace("_", " ").title()

    @classmethod
    def create_agent(cls, name: str, agent_id: str, user_id: str, workspace_id: str, **kwargs) -> BaseAgent | None:
        """Create an agent instance"""
        agent_class = cls.get_agent_class(name)
        if not agent_class:
            raise ValueError(f"Unknown agent: {name}")

        return agent_class(agent_id, user_id, workspace_id, **kwargs)


# ─────────────────────────────────────────────────────────────────────────
# Manual agent registration
#
# Most agents now self-register via `@register_agent` from the
# `agents/` subpackage and are auto-discovered at app startup by
# `AgentsCLIConfig.ready()`. See ADR 0003.
#
# All agents — including `ai_teammate` — now self-register via
# `@register_agent` from the `agents/` subpackage. The legacy
# `OrchestratorAgent` ReAct class has been retired; see
# `agents/ai_teammate_agent.py` for the LangGraph-native replacement
# and `application/services/detector_cycle.py` for the cron path.
# ─────────────────────────────────────────────────────────────────────────
