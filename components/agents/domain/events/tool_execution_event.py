"""Domain events emitted by tool executions.

These events carry cost, latency, and token metadata so that
downstream subscribers (budgeting, reports, notifications) can
build observability without coupling to the agents context.

Pure domain — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ToolExecutionCompletedEvent:
    """Emitted when a tool invocation completes (success or failure).

    Subscribers:
    - **reports** context: aggregate cost/usage dashboards
    - **budgeting** context: enforce spend limits per workspace
    - **notifications** context: alert on anomalous latency or cost
    """

    event_id: UUID = field(default_factory=uuid4)
    event_type: str = "tool_execution.completed"
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Identity
    execution_id: UUID = field(default_factory=uuid4)
    tool_id: UUID = field(default_factory=uuid4)
    agent_id: UUID = field(default_factory=uuid4)
    workspace_id: UUID = field(default_factory=uuid4)

    # What happened
    operation: str = ""
    access_strategy: str = ""
    execution_mode: str = ""     # "llm", "rules", "cached"
    success: bool = True
    error_message: Optional[str] = None

    # Cost metrics
    execution_time_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_name: str = ""
    model_tier: str = ""
    estimated_cost_usd: float = 0.0
    cache_hit: bool = False

    # Extensible metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionBatchCompletedEvent:
    """Emitted when an entire batch of tool calls completes.

    Carries aggregate metrics for the batch so subscribers can track
    batch efficiency (e.g. single-transaction ORM batches vs N+1).
    """

    event_id: UUID = field(default_factory=uuid4)
    event_type: str = "tool_execution.batch_completed"
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Identity
    workspace_id: UUID = field(default_factory=uuid4)
    agent_id: UUID = field(default_factory=uuid4)
    access_strategy: str = ""

    # Aggregate metrics
    batch_size: int = 0
    total_execution_time_ms: int = 0
    total_tokens: int = 0
    total_estimated_cost_usd: float = 0.0
    success_count: int = 0
    failure_count: int = 0

    # Per-item summary (tool_id → success/fail)
    item_results: Dict[str, bool] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CostThresholdExceededEvent:
    """Emitted when a workspace's cumulative tool execution cost
    exceeds a configured threshold.

    This allows the budgeting context to enforce spend limits and
    the notifications context to send alerts.
    """

    event_id: UUID = field(default_factory=uuid4)
    event_type: str = "tool_execution.cost_threshold_exceeded"
    timestamp: datetime = field(default_factory=datetime.utcnow)

    workspace_id: UUID = field(default_factory=uuid4)
    threshold_usd: float = 0.0
    current_spend_usd: float = 0.0
    period: str = "daily"       # "daily", "weekly", "monthly"
    metadata: Dict[str, Any] = field(default_factory=dict)
