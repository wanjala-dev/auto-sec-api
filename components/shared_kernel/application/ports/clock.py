from __future__ import annotations

from datetime import date, datetime
from typing import Protocol


class Clock(Protocol):
    """Time source used by application and domain code."""

    def now(self) -> datetime: ...

    def today(self) -> date: ...
