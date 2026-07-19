"""ToolExecution — child entity of ToolEntity, owned by the Tool AR.

Records the outcome of a single tool invocation: which access strategy
was used, how many tokens were consumed, latency, cost, and whether the
call was served from cache or handled by rules-based logic.

This is a pure domain entity — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from components.agents.domain.enums import (
    ExecutionMode,
    ModelTier,
    ToolExecutionStatus,
)


@dataclass(frozen=True)
class TokenUsage:
    """Immutable value object capturing LLM token consumption."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_name: str = ""
    model_tier: str = ModelTier.TIER_1

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate using tier multipliers.

        Real billing should come from the LLM provider; this is for
        domain-level budgeting and observability.
        """
        base_rate_per_1k = 0.0005  # baseline cost per 1k tokens
        multiplier = ModelTier.COST_MULTIPLIERS.get(self.model_tier, 1.0)
        return (self.total_tokens / 1000) * base_rate_per_1k * multiplier


@dataclass
class ToolExecutionEntity:
    """Child entity: a single invocation of a Tool.

    Owned by the Tool AR — the tool_id foreign key establishes
    the aggregate boundary.

    Invariants:
    - ``execution_time_ms`` must be non-negative when set.
    - ``status`` must follow valid transitions (pending → running → completed|failed).
    - ``execution_mode`` determines whether token_usage is relevant.
    """

    execution_id: UUID
    tool_id: UUID
    agent_id: UUID
    workspace_id: UUID

    # What was requested
    operation: str
    params: Dict[str, Any] = field(default_factory=dict)

    # How it was handled
    execution_mode: str = ExecutionMode.LLM
    access_strategy: str = ""  # Copied from tool at execution time
    status: str = ToolExecutionStatus.PENDING

    # Results
    result: Optional[Any] = None
    error_message: Optional[str] = None

    # Cost & performance metrics
    execution_time_ms: Optional[int] = None
    token_usage: Optional[TokenUsage] = None
    cache_hit: bool = False

    # Metadata
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # ── Factory methods ──────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        tool_id: UUID,
        agent_id: UUID,
        workspace_id: UUID,
        operation: str,
        access_strategy: str,
        params: Dict[str, Any] | None = None,
        execution_mode: str = ExecutionMode.LLM,
    ) -> "ToolExecutionEntity":
        """Factory for a new execution record (pre-persist)."""
        cls._validate_execution_mode(execution_mode)
        return cls(
            execution_id=uuid4(),
            tool_id=tool_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            operation=operation,
            access_strategy=access_strategy,
            params=params or {},
            execution_mode=execution_mode,
            created_at=datetime.utcnow(),
        )

    @classmethod
    def rehydrate(cls, **kwargs) -> "ToolExecutionEntity":
        """Reconstitute from persistence."""
        return cls(**kwargs)

    # ── Domain logic ─────────────────────────────────────────────────

    def mark_running(self) -> None:
        if self.status != ToolExecutionStatus.PENDING:
            raise ValueError(
                f"Cannot start execution in status {self.status!r}"
            )
        self.status = ToolExecutionStatus.RUNNING

    def mark_completed(
        self,
        *,
        result: Any,
        execution_time_ms: int,
        token_usage: TokenUsage | None = None,
        cache_hit: bool = False,
    ) -> None:
        """Record a successful execution."""
        self._validate_execution_time(execution_time_ms)
        self.status = ToolExecutionStatus.COMPLETED
        self.result = result
        self.execution_time_ms = execution_time_ms
        self.token_usage = token_usage
        self.cache_hit = cache_hit
        self.completed_at = datetime.utcnow()

    def mark_failed(
        self,
        *,
        error_message: str,
        execution_time_ms: int = 0,
    ) -> None:
        """Record a failed execution."""
        self.status = ToolExecutionStatus.FAILED
        self.error_message = error_message
        self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def mark_skipped(self, *, reason: str = "rules_based") -> None:
        """Mark as skipped — rules-based policy bypassed the call."""
        self.status = ToolExecutionStatus.SKIPPED
        self.error_message = reason
        self.execution_mode = ExecutionMode.RULES_BASED
        self.execution_time_ms = 0
        self.completed_at = datetime.utcnow()

    @property
    def is_billable(self) -> bool:
        """Only LLM-mode executions with token usage are billable."""
        return (
            self.execution_mode == ExecutionMode.LLM
            and self.token_usage is not None
            and self.token_usage.total_tokens > 0
            and not self.cache_hit
        )

    @property
    def cost_usd(self) -> float:
        """Estimated cost in USD.  Zero for non-billable executions."""
        if not self.is_billable or self.token_usage is None:
            return 0.0
        return self.token_usage.estimated_cost_usd

    @property
    def latency_bucket(self) -> str:
        """Classify latency for observability dashboards."""
        if self.execution_time_ms is None:
            return "unknown"
        if self.execution_time_ms < 200:
            return "fast"
        if self.execution_time_ms < 1000:
            return "normal"
        if self.execution_time_ms < 5000:
            return "slow"
        return "very_slow"

    # ── Invariant validation ─────────────────────────────────────────

    @staticmethod
    def _validate_execution_mode(mode: str) -> None:
        if mode not in ExecutionMode.ALL:
            raise ValueError(
                f"Invalid execution mode {mode!r}. "
                f"Must be one of: {', '.join(ExecutionMode.ALL)}"
            )

    @staticmethod
    def _validate_execution_time(ms: int) -> None:
        if ms < 0:
            raise ValueError(
                f"execution_time_ms must be non-negative, got {ms}"
            )
