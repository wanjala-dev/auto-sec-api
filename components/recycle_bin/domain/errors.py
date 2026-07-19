"""Recycle bin domain errors.

Sub-classes of the shared exception taxonomy so controllers and
middleware can catch at the taxonomy level for uniform HTTP mapping
while still surfacing context-specific semantics.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
)


class RecycleBinError(DomainError):
    """Base error for recycle bin domain invariant violations."""


class EntryNotFoundError(NotFoundError, RecycleBinError):
    def __init__(self, entry_id):
        super().__init__(f"Recycle bin entry not found: {entry_id}")


class EntryNotRestorableError(RecycleBinError):
    def __init__(self, entry_id, stage):
        super().__init__(
            f"Entry {entry_id} in stage '{stage}' cannot be restored by this action"
        )


class EntityAlreadyTrashedError(ConflictError, RecycleBinError):
    def __init__(self, entity_type, entity_id):
        super().__init__(f"{entity_type} {entity_id} is already in the recycle bin")
