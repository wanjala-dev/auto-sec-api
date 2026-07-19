"""Audit-log port for the recycle bin context.

Lifecycle transitions a row goes through:

    active --(trash)--> trashed --(restore)--> active
                                \\
                                 +-(purge / expire)--> purged (no row)

Every transition emits exactly one audit event via this port. The port
captures actor + timestamp on every call so we can answer "who deleted
this and when" without a reason. The reason field is optional -- when
present it answers "why" too.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class AuditLogPort(ABC):
    """Application-facing interface for recycle-bin audit events."""

    @abstractmethod
    def log_trash(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> None:
        """Record that ``entity_id`` was moved into the recycle bin."""

    @abstractmethod
    def log_restore(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> None:
        """Record that ``entity_id`` was restored out of the recycle bin."""

    @abstractmethod
    def log_purge(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> None:
        """Record that ``entity_id`` was permanently deleted."""
