"""Request DTOs for message endpoints.

Input data classes for POST /social/message and related endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateMessageRequest:
    """Input DTO for POST /social/message/ endpoint."""
    body: str
    thread: str
    sender_user: str | None = None
    receiver_user: str | None = None
    image: str | None = None
    workspace_id: str | None = None


@dataclass(frozen=True)
class UpdateMessageRequest:
    """Input DTO for PUT/PATCH /social/message/<id>/ endpoint."""
    body: str | None = None
    is_read: bool | None = None
