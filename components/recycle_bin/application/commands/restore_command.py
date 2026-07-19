from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RestoreCommand:
    entry_id: UUID
    restored_by: UUID
    # Optional reason captured at restore time — useful for "why is
    # this back?" investigations. Empty string is fine; the audit row
    # still records the restorer + timestamp.
    reason: str = ""
