"""Response DTOs for the deep-run observability endpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from components.agents.application.ports.deep_run_query_port import (
    DeepRunEventView,
    DeepRunSnapshotView,
    DeepRunStatsView,
    DeepRunSubagentView,
)


def _iso(value):
    return value.isoformat() if value else None


def _canonical_name(agent_type: str) -> str:
    """Resolve an alias-or-slug to its canonical registered name.

    The planner may emit the alias slug it chose from the dynamic
    agent catalog (e.g. ``letter_agent`` for the writing agent). The
    chat header should always render the canonical slug
    (``writing_agent``) so users see a consistent identity across
    runs. Falls back to the raw agent_type if the registry isn't
    importable or the slug is a routing sentinel like ``clarify``.
    """
    if not agent_type:
        return ""
    try:
        from components.agents.application.providers.agent_registry_provider import (
            get_agent_registry_provider,
        )
        AgentRegistry = get_agent_registry_provider()
    except ImportError:  # pragma: no cover — defensive
        return agent_type
    return AgentRegistry.canonical_name_for(agent_type)


def _display_name(agent_type: str) -> str:
    """Resolve an alias-or-slug to a human-readable display label.

    Reads ``profile['name']`` from the registered class when present
    (e.g. ``"Writing Agent"``). Falls back to a titlecased version of
    the canonical slug. The frontend prefers this over the raw slug
    for the chat header so users see ``Writing Agent`` not
    ``writing_agent``.
    """
    if not agent_type:
        return ""
    try:
        from components.agents.application.providers.agent_registry_provider import (
            get_agent_registry_provider,
        )
        AgentRegistry = get_agent_registry_provider()
    except ImportError:  # pragma: no cover
        return agent_type.replace("_", " ").title()
    return AgentRegistry.display_name_for(agent_type)


@dataclass(frozen=True)
class DeepRunSubagentResource:
    task_id: str
    agent_type: str
    # Canonical slug + human label, resolved via AgentRegistry. Both
    # are additive — ``agent_type`` keeps whatever the planner emitted
    # (alias-aware) so existing consumers stay unaffected. Frontend
    # prefers ``agent_display_name`` for the chat header so users see
    # a consistent ``Writing Agent`` regardless of which alias the
    # planner picked.
    agent_canonical_name: str
    agent_display_name: str
    status: str
    started_at: str | None
    completed_at: str | None
    tool_calls: list = field(default_factory=list)

    @classmethod
    def from_view(cls, view: DeepRunSubagentView) -> "DeepRunSubagentResource":
        return cls(
            task_id=view.task_id,
            agent_type=view.agent_type,
            agent_canonical_name=_canonical_name(view.agent_type),
            agent_display_name=_display_name(view.agent_type),
            status=view.status,
            started_at=_iso(view.started_at),
            completed_at=_iso(view.completed_at),
            tool_calls=list(view.tool_calls),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DeepRunSnapshotResource:
    plan_id: str
    thread_id: str
    workspace_id: str | None
    user_id: str
    status: str
    progress_percent: int
    goal: str
    agent_type: str
    agent_canonical_name: str
    agent_display_name: str
    task_count: int
    completed_task_count: int
    started_at: str
    updated_at: str
    last_error: str
    subagents: list

    @classmethod
    def from_view(cls, view: DeepRunSnapshotView) -> "DeepRunSnapshotResource":
        return cls(
            plan_id=view.plan_id,
            thread_id=view.thread_id,
            workspace_id=view.workspace_id,
            user_id=view.user_id,
            status=view.status,
            progress_percent=view.progress_percent,
            goal=view.goal,
            agent_type=view.agent_type,
            agent_canonical_name=_canonical_name(view.agent_type),
            agent_display_name=_display_name(view.agent_type),
            task_count=view.task_count,
            completed_task_count=view.completed_task_count,
            started_at=_iso(view.started_at) or "",
            updated_at=_iso(view.updated_at) or "",
            last_error=view.last_error,
            subagents=[DeepRunSubagentResource.from_view(s).to_dict() for s in view.subagents],
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DeepRunEventResource:
    id: int
    timestamp: str
    event_type: str
    status: str
    agent_type: str
    tool_name: str
    payload: dict

    @classmethod
    def from_view(cls, view: DeepRunEventView) -> "DeepRunEventResource":
        return cls(
            id=view.id,
            timestamp=_iso(view.timestamp) or "",
            event_type=view.event_type,
            status=view.status,
            agent_type=view.agent_type,
            tool_name=view.tool_name,
            payload=view.payload,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DeepRunStatsResource:
    workspace_id: str | None
    total_runs: int
    runs_by_status: dict
    runs_by_agent_type: dict
    tool_call_counts: dict
    failure_rate: float
    window_started_at: str | None

    @classmethod
    def from_view(cls, view: DeepRunStatsView) -> "DeepRunStatsResource":
        return cls(
            workspace_id=view.workspace_id,
            total_runs=view.total_runs,
            runs_by_status=view.runs_by_status,
            runs_by_agent_type=view.runs_by_agent_type,
            tool_call_counts=view.tool_call_counts,
            failure_rate=view.failure_rate,
            window_started_at=_iso(view.window_started_at),
        )

    def to_dict(self) -> dict:
        return asdict(self)
