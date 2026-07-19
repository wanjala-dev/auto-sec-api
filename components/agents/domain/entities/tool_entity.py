"""Tool Aggregate Root — a first-class capability an AI agent can invoke.

A Tool has identity, configuration, required permissions, and an
**access strategy** that determines *how* it reaches external resources.

This is a pure domain entity — no ORM, no LangChain, no framework imports.

Access strategies (file, MCP, web, ORM/database) are modeled as an enum
on the AR; the actual strategy implementation lives behind the
``ToolAccessPort`` (an intra-context port defined in ``agents/ports/``).

Cost optimisation:
- ``model_tier`` — preferred LLM tier (overridable by ``ModelSelectionPolicy``).
- ``cacheable`` — whether results can be cached by ``CachingToolAccessAdapter``.
- ``cache_ttl_seconds`` — per-tool cache TTL override.
- ``require_llm`` — force LLM execution even for deterministic operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from components.agents.domain.enums import ModelTier, ToolAccessStrategy, ToolStatus


@dataclass(frozen=True)
class ToolPermission:
    """Permission required to invoke a tool."""

    action: str  # e.g. "budget:read", "task:write", "news:*"
    scope_type: str = "workspace"
    description: str = ""


@dataclass(frozen=True)
class ToolSchema:
    """Input/output schema for a tool — framework-agnostic."""

    input_fields: dict[str, Any] = field(default_factory=dict)
    output_fields: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class ToolEntity:
    """Aggregate Root for a tool that an AI agent can use.

    Invariants:
    - ``slug`` must be non-empty and URL-safe.
    - ``access_strategy`` must be a valid ``ToolAccessStrategy``.
    - A disabled tool must not be invocable.
    """

    tool_id: UUID
    slug: str
    name: str
    description: str
    access_strategy: str  # ToolAccessStrategy value
    agent_type: str  # which agent type owns this tool
    status: str = ToolStatus.ACTIVE

    # Configuration
    config: dict[str, Any] = field(default_factory=dict)
    schema: ToolSchema = field(default_factory=ToolSchema)
    required_permissions: list[ToolPermission] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Access-strategy-specific config
    access_config: dict[str, Any] = field(default_factory=dict)
    # Examples:
    #   ORM:  {"model_paths": ["infrastructure.persistence.project.models.Project"]}
    #   MCP:  {"server_name": "project-mcp", "tool_name": "list_projects"}
    #   WEB:  {"base_url": "https://api.example.com", "auth_header": "..."}
    #   FILE: {"allowed_paths": ["/data/exports/"], "formats": ["csv", "json"]}

    # ── Cost optimisation config ─────────────────────────────────────
    model_tier: str = ModelTier.TIER_2  # Preferred LLM tier
    cacheable: bool = True  # Allow caching adapter
    cache_ttl_seconds: int = 300  # Per-tool cache TTL
    require_llm: bool = False  # Force LLM even for simple ops
    max_batch_size: int = 10  # Max items in a single batch

    # ── Concurrency config ───────────────────────────────────────────
    is_read_only: bool = True  # Safe for concurrent execution

    # Metadata
    workspace_id: UUID | None = None  # None = global tool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # ── Factory methods ──────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        slug: str,
        name: str,
        description: str,
        access_strategy: str,
        agent_type: str,
        config: dict[str, Any] | None = None,
        required_permissions: list[ToolPermission] | None = None,
        access_config: dict[str, Any] | None = None,
        workspace_id: UUID | None = None,
        tags: list[str] | None = None,
    ) -> ToolEntity:
        """Factory for brand-new tools (pre-persist)."""
        cls._validate_slug(slug)
        cls._validate_access_strategy(access_strategy)

        now = datetime.utcnow()
        return cls(
            tool_id=uuid4(),
            slug=slug,
            name=name,
            description=description,
            access_strategy=access_strategy,
            agent_type=agent_type,
            config=config or {},
            required_permissions=required_permissions or [],
            access_config=access_config or {},
            workspace_id=workspace_id,
            tags=tags or [],
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def rehydrate(cls, **kwargs) -> ToolEntity:
        """Factory for reconstituting from persistence."""
        return cls(**kwargs)

    # ── Domain logic ─────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self.status == ToolStatus.ACTIVE

    @property
    def is_orm_tool(self) -> bool:
        return self.access_strategy == ToolAccessStrategy.ORM

    @property
    def is_mcp_tool(self) -> bool:
        return self.access_strategy == ToolAccessStrategy.MCP

    @property
    def is_web_tool(self) -> bool:
        return self.access_strategy == ToolAccessStrategy.WEB

    @property
    def is_file_tool(self) -> bool:
        return self.access_strategy == ToolAccessStrategy.FILE

    @property
    def is_concurrency_safe(self) -> bool:
        """Whether this tool can run concurrently with other read-only tools."""
        return self.is_read_only and self.is_active

    def disable(self) -> None:
        self.status = ToolStatus.DISABLED
        self.updated_at = datetime.utcnow()

    def enable(self) -> None:
        self.status = ToolStatus.ACTIVE
        self.updated_at = datetime.utcnow()

    def requires_permission(self, action: str) -> bool:
        """Check if this tool requires a specific permission."""
        if not self.required_permissions:
            return False
        return any(p.action == action or p.action.endswith(":*") for p in self.required_permissions)

    def check_permissions(self, granted_actions: list[str]) -> bool:
        """Return True if all required permissions are satisfied."""
        if not self.required_permissions:
            return True
        for perm in self.required_permissions:
            if perm.action in granted_actions:
                continue
            # Check wildcard: "budget:*" satisfies "budget:read"
            domain = perm.action.split(":")[0] + ":*"
            if domain in granted_actions or "*" in granted_actions:
                continue
            return False
        return True

    # ── Cost optimisation logic ──────────────────────────────────────

    @property
    def is_cacheable(self) -> bool:
        """Whether this tool's results may be cached."""
        return self.cacheable and self.is_active

    @property
    def cost_multiplier(self) -> float:
        """Relative cost multiplier based on the preferred model tier."""
        return ModelTier.COST_MULTIPLIERS.get(self.model_tier, 1.0)

    @property
    def is_cheap_tool(self) -> bool:
        """True if this tool uses the lowest-cost tier."""
        return self.model_tier == ModelTier.TIER_1

    @property
    def is_expensive_tool(self) -> bool:
        """True if this tool uses the highest-cost tier."""
        return self.model_tier == ModelTier.TIER_3

    def supports_batching(self) -> bool:
        """Whether this tool can participate in batch executions.

        MCP and WEB tools support batching when the server/API allows it.
        ORM tools can batch within a single DB transaction.
        FILE tools are sequential by nature.
        """
        if not self.is_active:
            return False
        if self.is_file_tool:
            return False
        return self.max_batch_size > 1

    def validate_batch_size(self, size: int) -> None:
        """Raise if the requested batch size exceeds the tool's limit."""
        if size > self.max_batch_size:
            raise ValueError(f"Batch size {size} exceeds max_batch_size {self.max_batch_size} for tool {self.slug!r}")

    def should_require_health_check(self) -> bool:
        """MCP and WEB tools should be health-checked before execution."""
        return self.is_mcp_tool or self.is_web_tool

    def get_effective_config(self) -> dict[str, Any]:
        """Return the tool config merged with cost-optimisation fields.

        This is the config dict that policies and resolvers consume.
        """
        return {
            **self.config,
            "model_tier": self.model_tier,
            "cacheable": self.cacheable,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "require_llm": self.require_llm,
            "max_batch_size": self.max_batch_size,
        }

    # ── Invariant validation ─────────────────────────────────────────

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if not slug or not slug.strip():
            raise ValueError("Tool slug must be non-empty")
        if not all(c.isalnum() or c in ("-", "_") for c in slug):
            raise ValueError(f"Tool slug must be URL-safe (alphanumeric, hyphens, underscores): {slug!r}")

    @staticmethod
    def _validate_access_strategy(strategy: str) -> None:
        if strategy not in ToolAccessStrategy.ALL:
            raise ValueError(
                f"Invalid access strategy {strategy!r}. Must be one of: {', '.join(ToolAccessStrategy.ALL)}"
            )
