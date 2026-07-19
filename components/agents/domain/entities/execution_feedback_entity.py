"""Per-response feedback — thumbs up/down on individual AI answers.

Unlike AgentRating (which rates the agent overall), this entity
captures quality signals on individual execution responses.

Pure domain entity — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class FeedbackSignal(StrEnum):
    """The user's verdict on a single AI response."""

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


@dataclass(frozen=True)
class ExecutionFeedbackEntity:
    """Feedback on a single agent execution response."""

    feedback_id: UUID
    execution_id: int
    user_id: UUID
    signal: str  # FeedbackSignal value
    comment: str = ""
    tags: list[str] | None = None  # e.g. ["inaccurate", "too_long", "helpful"]
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        execution_id: int,
        user_id: UUID,
        signal: str,
        comment: str = "",
        tags: list[str] | None = None,
    ) -> ExecutionFeedbackEntity:
        if signal not in (FeedbackSignal.THUMBS_UP, FeedbackSignal.THUMBS_DOWN):
            raise ValueError(f"Invalid feedback signal: {signal}")
        return cls(
            feedback_id=uuid4(),
            execution_id=execution_id,
            user_id=user_id,
            signal=signal,
            comment=comment,
            tags=tags,
            created_at=datetime.utcnow(),
        )

    @property
    def is_positive(self) -> bool:
        return self.signal == FeedbackSignal.THUMBS_UP

    @property
    def is_negative(self) -> bool:
        return self.signal == FeedbackSignal.THUMBS_DOWN
