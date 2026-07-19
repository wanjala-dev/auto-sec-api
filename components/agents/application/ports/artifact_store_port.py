"""Port for artifact storage and retrieval.

Artifacts are persisted execution outputs from deep-agent runs (plans,
reports, code, summaries). The port abstracts the storage backend so
the application layer can store and reference artifacts without knowing
whether they live in Django ORM rows, object storage, or elsewhere.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArtifactReference:
    """Lightweight reference to a stored artifact, suitable for prompts."""
    uri: str = ""
    summary: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRecord:
    """Full artifact payload retrieved from storage."""
    id: str = ""
    uri: str = ""
    run_id: str | None = None
    task_id: str = ""
    summary: str = ""
    data: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class ArtifactStorePort(ABC):
    """Abstract contract for artifact persistence."""

    @abstractmethod
    def store(
        self,
        payload: dict,
        *,
        kind: str = "generic",
        metadata: dict | None = None,
        run_thread_id: str | None = None,
        task_id: str | None = None,
    ) -> ArtifactReference:
        """Persist an artifact and return a lightweight reference."""
        ...

    @abstractmethod
    def get_by_uri(self, uri: str) -> ArtifactRecord | None:
        """Retrieve an artifact by its URI. Returns None if not found."""
        ...

    @abstractmethod
    def list_by_run(self, run_thread_id: str) -> list[ArtifactRecord]:
        """List all artifacts for a given run thread."""
        ...
