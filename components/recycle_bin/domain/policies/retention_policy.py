from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RetentionPolicy:
    trash_retention_days: int = 30
    tombstone_retention_days: int = 30

    def trashed_until(self, deleted_at: datetime) -> datetime:
        return deleted_at + timedelta(days=self.trash_retention_days)

    def tombstoned_until(self, tombstoned_at: datetime) -> datetime:
        return tombstoned_at + timedelta(days=self.tombstone_retention_days)
