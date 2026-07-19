"""Commands and result types for PDF conversation chat.

Framework-free — used by PdfChatUseCase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.shared_kernel.application.commands import Command


@dataclass(frozen=True, kw_only=True)
class PdfChatCommand(Command):
    """Everything the use case needs to process a PDF chat message."""

    conversation_id: UUID
    user_id: UUID
    pdf_id: str
    workspace_id: str
    query: str
    chat_history: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PdfChatSuccess:
    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PdfChatNoContent:
    """PDF exists but no indexed chunks were found."""

    pdf_id: str
    workspace_id: str
    error: str = "No content found for this document. Please make sure it has been processed."


@dataclass(frozen=True)
class PdfChatNoRelevantDocs:
    """Chunks exist but nothing matched the query after all fallback strategies."""

    pdf_id: str
    workspace_id: str
    error: str = "Could not find relevant information for your question."


@dataclass(frozen=True)
class PdfChatFailure:
    error: str
    status_code: int = 500
