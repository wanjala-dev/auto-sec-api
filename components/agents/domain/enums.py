"""AI bounded-context domain enumerations.

Pure Python — no framework imports.  These replace the status/choice
constants scattered across the ORM models so that domain and application
layers can reference them without touching Django.
"""

from __future__ import annotations


# ── Agent lifecycle ──────────────────────────────────────────────────

class AgentStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"

    ALL = frozenset({ACTIVE, PAUSED, COMPLETED, ERROR})


class ExecutionStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    ALL = frozenset({PENDING, RUNNING, COMPLETED, FAILED})


# ── AI actions ───────────────────────────────────────────────────────

class ActionStatus:
    PENDING = "pending"
    AUTO_EXECUTED = "auto_executed"
    APPROVED = "approved"
    REVERTED = "reverted"
    DISMISSED = "dismissed"

    ALL = frozenset({PENDING, AUTO_EXECUTED, APPROVED, REVERTED, DISMISSED})

    # Valid transitions: from_status → {allowed targets}
    TRANSITIONS: dict[str, frozenset[str]] = {
        PENDING: frozenset({AUTO_EXECUTED, APPROVED, DISMISSED}),
        AUTO_EXECUTED: frozenset({REVERTED}),
        APPROVED: frozenset({REVERTED}),
        REVERTED: frozenset(),
        DISMISSED: frozenset(),
    }


class ActionEventType:
    CREATED = "created"
    AUTO_EXECUTED = "auto_executed"
    APPROVED = "approved"
    REVERTED = "reverted"
    DISMISSED = "dismissed"
    NOTE = "note"
    ERROR = "error"


class ActorType:
    AI = "ai"
    ADMIN = "admin"
    SYSTEM = "system"

    ALL = frozenset({AI, ADMIN, SYSTEM})


# ── Conversations ────────────────────────────────────────────────────

class MessageRole:
    HUMAN = "human"
    ASSISTANT = "assistant"
    SYSTEM = "system"

    ALL = frozenset({HUMAN, ASSISTANT, SYSTEM})


# ── AI Teammate / Permissions ────────────────────────────────────────

class TeammateStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"

    ALL = frozenset({ACTIVE, PAUSED, DISABLED})


class PermissionRole:
    AI_EXECUTOR = "ai_executor"


class PermissionScope:
    WORKSPACE = "workspace"
    DEPARTMENT = "department"
    PROJECT = "project"

    ALL = frozenset({WORKSPACE, DEPARTMENT, PROJECT})


# ── Agent profile / social ───────────────────────────────────────────

class AgentVisibility:
    WORKSPACE_ONLY = "workspace_only"
    SHARED_LINK = "shared_link"

    ALL = frozenset({WORKSPACE_ONLY, SHARED_LINK})


class ShareScope:
    WORKSPACE_ONLY = "workspace_only"
    PUBLIC = "public"

    ALL = frozenset({WORKSPACE_ONLY, PUBLIC})


# ── Tool access strategies ──────────────────────────────────────────

class ToolAccessStrategy:
    ORM = "orm"       # Direct database queries (Django ORM)
    MCP = "mcp"       # Model Context Protocol server
    WEB = "web"       # HTTP/REST API calls
    FILE = "file"     # Local filesystem access

    ALL = frozenset({ORM, MCP, WEB, FILE})


class ToolStatus:
    ACTIVE = "active"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"

    ALL = frozenset({ACTIVE, DISABLED, DEPRECATED})


# ── Deep runs ────────────────────────────────────────────────────────

class DeepRunStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    ALL = frozenset({PENDING, RUNNING, COMPLETED, FAILED})


# ── Cost optimization ────────────────────────────────────────────────

class ModelTier:
    """Complexity tier for LLM model selection.

    Policies map task complexity to a tier; the LLM provider registry
    resolves the tier to a concrete model slug at runtime.
    """

    TIER_1 = "tier_1"   # Cheapest — classification, extraction, simple Q&A
    TIER_2 = "tier_2"   # Mid-range — summarisation, moderate reasoning
    TIER_3 = "tier_3"   # Highest — multi-step reasoning, planning, code gen

    ALL = frozenset({TIER_1, TIER_2, TIER_3})

    # Default cost multipliers (relative to tier_1)
    COST_MULTIPLIERS: dict[str, float] = {
        TIER_1: 1.0,
        TIER_2: 5.0,
        TIER_3: 20.0,
    }


class ExecutionMode:
    """Whether a tool invocation requires an LLM or can be handled by
    deterministic rules-based logic.

    The ``ToolExecutionPolicy`` evaluates the request and selects the
    mode; downstream routing honours this decision.
    """

    LLM = "llm"               # Requires LLM reasoning
    RULES_BASED = "rules"     # Deterministic — skip the LLM entirely
    CACHED = "cached"         # Serve from cache — no execution needed

    ALL = frozenset({LLM, RULES_BASED, CACHED})


class ToolExecutionStatus:
    """Lifecycle of a single tool invocation."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"        # Rules-based policy bypassed tool call

    ALL = frozenset({PENDING, RUNNING, COMPLETED, FAILED, SKIPPED})
