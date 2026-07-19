"""Request DTO for sending a message."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SendMessageRequest:
    """Input DTO for sending a message in a conversation.

    ``body`` defaults to empty so an image-only message is valid; the
    uploaded image itself is passed separately (it isn't a plain field).
    """

    body: str = ""
    message_type: str = "text"
