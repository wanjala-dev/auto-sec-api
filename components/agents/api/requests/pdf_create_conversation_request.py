"""Request DTO for POST /ai/conversations/create/ endpoint (PDF variant)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PdfCreateConversationRequest:
    """Input DTO for POST /ai/conversations/create/ endpoint (PDF variant).

    Creates a new conversation for PDF document interaction.
    """
    pdf_id: str
    workspace_id: str | None = None
    title: str | None = None
