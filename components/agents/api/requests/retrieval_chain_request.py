"""Request DTO for POST /ai/chains/retrieval/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalChainRequest:
    """Input DTO for POST /ai/chains/retrieval/ endpoint.

    Executes a retrieval-augmented generation chain.
    """
    question: str
    pdf_id: str | None = None
    workspace_id: str | None = None
    k: int = 5
    stream: bool = False
    config: dict[str, Any] = field(default_factory=dict)
