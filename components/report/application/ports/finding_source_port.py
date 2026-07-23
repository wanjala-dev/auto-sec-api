"""Port: read scoped board findings for a report.

The assembler depends on this interface, not on the ORM. The adapter
(``infrastructure/repositories/board_finding_repository.py``) implements it by
reading ``project.Task`` rows tagged ``source_type`` ``ai.*``.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


class FindingSourcePort(abc.ABC):
    """Reads the findings a report pulls, as plain dicts."""

    @abc.abstractmethod
    def list_findings(
        self,
        *,
        workspace_id: str,
        source_type_prefixes: Sequence[str],
        source_types: Sequence[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ) -> list[Mapping[str, Any]]:
        """Return scoped findings, newest first.

        Args:
            workspace_id: the workspace whose board is read.
            source_type_prefixes: the kind's ``ai.`` prefixes — a finding is in
                scope when its ``source_type`` starts with any of them.
            source_types: optional explicit ``source_type`` allow-list the
                operator selected (narrows within the prefixes).
            since / until: optional created-at window.
            limit: hard cap on findings pulled.

        Each dict carries at least ``id``, ``title``, ``description``,
        ``source_type``, ``status``, ``created_at`` and ``metadata``.
        """
        raise NotImplementedError
