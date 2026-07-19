"""Resource DTOs for message endpoints.

Output data classes for GET /social/message endpoints and responses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MessageResource:
    """Output DTO for message detail endpoints."""
    id: str
    body: str
    date: str | None = None
    thread: str | None = None
    sender_user: str | None = None
    receiver_user: str | None = None
    is_read: bool = False
    image: str | None = None
    workspace: str | None = None


@dataclass(frozen=True)
class MessageCollectionResource:
    """Output DTO for message list endpoints."""
    items: list[MessageResource]
    count: int = 0
