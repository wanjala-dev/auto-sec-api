"""Output DTOs for timer endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimerEntryResource:
    """Output DTO for timer operation endpoints (POST /api/projects/tasks/timer/start_timer/, etc.)."""
    success: bool | None = None
    entry_id: str | int | None = None
    total_tracked_minutes: int | None = None
    message: str | None = None
