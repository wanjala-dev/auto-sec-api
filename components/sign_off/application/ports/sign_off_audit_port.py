"""Audit sink for sign-off decisions.

Every transition (submitted / approved / changes-requested / rejected) records
an immutable entry — who, when, the risk band at decision time, and any
override reason. The production adapter writes to the shared ``EntityAuditLog``
(reused, not forked) in a later phase; Phase 1 ships the port + an in-memory
fake for tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SignOffAuditPort(ABC):
    @abstractmethod
    def record(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        event: str,
        actor_id: str | None,
        detail: dict | None = None,
    ) -> None:
        """Append an immutable audit entry for a sign-off decision."""
