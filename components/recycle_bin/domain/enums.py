from enum import StrEnum


class DeletionStage(StrEnum):
    TRASHED = "trashed"
    TOMBSTONED = "tombstoned"
