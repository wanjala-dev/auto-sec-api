"""Resource DTO: a WorkspaceLogSource payload for the REST adapter (ADR 0008)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LogSourceResource:
    """Serialized ``WorkspaceLogSource``.

    ``config`` is safe to expose: 3P credentials never live in it (they ride on
    ``secret_ref`` via the secret envelope), so no scrubbing is needed here.
    """

    id: str
    kind: str
    name: str
    config: dict
    status: str
    last_verified_at: str | None
    last_error: str
    created_at: str | None

    @classmethod
    def from_model(cls, source) -> LogSourceResource:
        return cls(
            id=str(source.id),
            kind=source.kind,
            name=source.name,
            config=source.config or {},
            status=source.status,
            last_verified_at=(source.last_verified_at.isoformat() if source.last_verified_at else None),
            last_error=source.last_error,
            created_at=(source.created_at.isoformat() if source.created_at else None),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "config": self.config,
            "status": self.status,
            "last_verified_at": self.last_verified_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
        }
