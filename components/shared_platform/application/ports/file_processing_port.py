"""Port for async file processing dispatch."""

from __future__ import annotations

from abc import ABC, abstractmethod


class FileProcessingPort(ABC):
    """Secondary/driven port for dispatching file processing tasks."""

    @abstractmethod
    def dispatch_pdf_processing(self, file_id: int) -> str | None:
        """Dispatch async PDF processing. Returns task ID or None."""
        ...

    @abstractmethod
    def dispatch_document_processing(self, file_id: int) -> str | None:
        """Dispatch async document processing. Returns task ID or None."""
        ...

    @abstractmethod
    def is_indexing_configured(self) -> bool:
        """Whether an embeddings provider is configured — an index request
        in an unconfigured environment must refuse loudly, not queue a
        task that no-ops."""
