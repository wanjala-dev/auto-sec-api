"""Request DTO for POST /ai/search/pdf/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchPdfContentRequest:
    """Input DTO for POST /ai/search/pdf/ endpoint.

    Searches document content using vector similarity.
    """
    query: str
    pdf_id: str
    workspace_id: str
    k: int = 10
