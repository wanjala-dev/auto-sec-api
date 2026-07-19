from __future__ import annotations

from datetime import UTC, date, datetime

from components.shared_kernel.application.ports.clock import Clock


class SystemClock(Clock):
    """Production clock adapter for application-layer time access."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()
