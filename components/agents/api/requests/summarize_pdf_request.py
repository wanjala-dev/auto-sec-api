"""Request DTO for POST /ai/summarize/pdf/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SummarizePdfRequest:
    """Input DTO for POST /ai/summarize/pdf/ endpoint.

    Generates a summary of PDF document content.
    """
    pdf_id: str
    workspace_id: str
    summary_type: str = "concise"
    max_length: int | None = None
    config: dict[str, Any] = field(default_factory=dict)
