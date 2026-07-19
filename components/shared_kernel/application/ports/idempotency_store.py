from __future__ import annotations

from typing import Protocol


class IdempotencyStore(Protocol):
    """Tracks whether a message or command has already been handled."""

    def claim(self, key: str) -> bool: ...

    def mark_completed(self, key: str) -> None: ...
