"""Request DTO for POST /ai/conversations/<id>/messages/create/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PdfCreateMessageRequest:
    """Input DTO for POST /ai/conversations/<id>/messages/create/ endpoint.

    Sends a message in a PDF conversation for chat-based interaction.
    """
    input: str
    stream: bool = False
