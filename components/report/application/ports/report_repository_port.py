"""Port: persist + read ``Report`` rows.

The use cases depend on this; the adapter wraps the ``report.Report`` ORM model.
Rows are represented to the application as plain dicts so the application layer
stays ORM-free.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import Any


class ReportRepositoryPort(abc.ABC):
    @abc.abstractmethod
    def create(
        self,
        *,
        workspace_id: str,
        kind: str,
        title: str,
        scope: Mapping[str, Any],
        created_by_id: str | None,
    ) -> Mapping[str, Any]:
        """Create a report row in ``draft`` status; return it as a dict."""

    @abc.abstractmethod
    def get(self, *, report_id: str, workspace_id: str) -> Mapping[str, Any] | None:
        """Fetch a report scoped to a workspace, or None."""

    @abc.abstractmethod
    def list(self, *, workspace_id: str, kind: str | None = None) -> list[Mapping[str, Any]]:
        """List a workspace's reports, newest first."""

    @abc.abstractmethod
    def mark_generating(self, *, report_id: str) -> None: ...

    @abc.abstractmethod
    def mark_generated(
        self,
        *,
        report_id: str,
        assembled: Mapping[str, Any],
        finding_count: int,
        pdf_key: str,
    ) -> None: ...

    @abc.abstractmethod
    def mark_failed(self, *, report_id: str, error_message: str) -> None: ...

    @abc.abstractmethod
    def mark_approved(self, *, report_id: str, approved_by_id: str) -> Mapping[str, Any]: ...
