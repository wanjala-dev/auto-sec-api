"""Request DTO for POST /ai/chains/qa/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QAChainRequest:
    """Input DTO for POST /ai/chains/qa/ endpoint.

    Executes a question-answering chain over documents.
    """
    question: str
    documents: list[str] = field(default_factory=list)
    chain_type: str = "stuff"
    config: dict[str, Any] = field(default_factory=dict)
