"""Response DTO for chain endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChainResponseResource:
    """Output DTO for chain execution endpoints."""
    response: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None
    tokens_used: int | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResultResource:
    """A single document result from retrieval chain."""
    content: str = ""
    document_id: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalChainResponseResource:
    """Output DTO for retrieval chain endpoints."""
    response: str = ""
    retrieved_documents: list[RetrievalResultResource] = field(default_factory=list)
    conversation_id: str | None = None
    tokens_used: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
