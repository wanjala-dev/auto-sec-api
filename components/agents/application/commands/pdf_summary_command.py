"""Commands and result types for the standalone PDF summarize endpoint.

Framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.shared_kernel.application.commands import Command


@dataclass(frozen=True, kw_only=True)
class PdfSummaryCommand(Command):
    """Input for the dedicated summarize-PDF use case."""

    pdf_id: str
    workspace_id: str
    user_id: str
    max_length: int = 500


@dataclass(frozen=True)
class PdfSummarySuccess:
    summary: str
    total_chunks: int
    word_count: int
    max_length: int
    model: str = ""
    usage: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PdfSummaryNoContent:
    pdf_id: str
    workspace_id: str
    error: str = "No content found. Please make sure the document has been processed."


@dataclass(frozen=True)
class PdfSummaryFailure:
    error: str
    status_code: int = 500
