"""Port: render report HTML to PDF bytes."""

from __future__ import annotations

import abc


class ReportPdfRendererPort(abc.ABC):
    @abc.abstractmethod
    def render(self, *, html: str, log_context: dict | None = None) -> bytes:
        """Return PDF bytes for ``html``. Raises on failure — never empty bytes."""
