"""Port for per-response feedback persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from components.agents.domain.entities.execution_feedback_entity import ExecutionFeedbackEntity


class ExecutionFeedbackPort(ABC):
    """Abstract contract for saving and querying execution feedback."""

    @abstractmethod
    def submit_feedback(self, feedback: ExecutionFeedbackEntity) -> None:
        """Save or update feedback for an execution."""
        ...

    @abstractmethod
    def get_feedback(self, execution_id: int) -> ExecutionFeedbackEntity | None:
        """Get feedback for a specific execution (if any)."""
        ...

    @abstractmethod
    def get_feedback_stats(self, agent_id: UUID) -> dict[str, Any]:
        """Aggregate feedback stats for an agent.

        Returns::
            {
                "total": 150,
                "thumbs_up": 120,
                "thumbs_down": 30,
                "positive_rate": 0.80,
                "common_tags": {"helpful": 45, "inaccurate": 12, ...},
            }
        """
        ...
