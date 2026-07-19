"""Request DTO for POST /ai/chat/images/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatWithImagesRequest:
    """Input DTO for POST /ai/chat/images/ endpoint.

    Chat about images using vision capabilities.
    """
    query: str
    image_urls: list[str] = field(default_factory=list)
    conversation_id: str | None = None
    stream: bool = False
    config: dict[str, Any] = field(default_factory=dict)
