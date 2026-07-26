from __future__ import annotations

from components.workspace.application.use_cases.start_timer_use_case import (
    StartTimerUseCase,
)
from components.workspace.application.use_cases.stop_timer_use_case import (
    StopTimerUseCase,
)
from components.workspace.application.use_cases.discard_timer_use_case import (
    DiscardTimerUseCase,
)
from components.workspace.infrastructure.repositories.time_tracking_repository import (
    OrmTimeTrackingRepository,
)


class TimeTrackingProvider:
    @staticmethod
    def build_start_timer() -> StartTimerUseCase:
        return StartTimerUseCase(port=OrmTimeTrackingRepository())

    @staticmethod
    def build_stop_timer() -> StopTimerUseCase:
        return StopTimerUseCase(port=OrmTimeTrackingRepository())

    @staticmethod
    def build_discard_timer() -> DiscardTimerUseCase:
        return DiscardTimerUseCase(port=OrmTimeTrackingRepository())

    @staticmethod
    def build_time_tracking_port() -> OrmTimeTrackingRepository:
        """Return the time-tracking read/write port (for callers that need the
        repository's query methods directly, e.g. the task agent's timer status)."""
        return OrmTimeTrackingRepository()
