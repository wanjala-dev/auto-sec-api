"""Resource DTO: a VcsConnection payload for the REST adapter (ADR 0010 Phase 3).

The token is NEVER exposed — only ``has_token`` (a boolean) tells the UI whether a
secret is stored. ``repo_allowlist`` (the consent boundary) is safe to return.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VcsConnectionResource:
    id: str
    provider: str
    name: str
    repo_allowlist: list
    base_url: str
    status: str
    has_token: bool
    last_verified_at: str | None
    last_used_at: str | None
    last_error: str
    created_at: str | None

    @classmethod
    def from_model(cls, connection) -> VcsConnectionResource:
        return cls(
            id=str(connection.id),
            provider=connection.provider,
            name=connection.name,
            repo_allowlist=connection.repo_allowlist or [],
            base_url=connection.base_url or "",
            status=connection.status,
            has_token=bool(connection.token_ciphertext),
            last_verified_at=(connection.last_verified_at.isoformat() if connection.last_verified_at else None),
            last_used_at=(connection.last_used_at.isoformat() if connection.last_used_at else None),
            last_error=connection.last_error,
            created_at=(connection.created_at.isoformat() if connection.created_at else None),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "name": self.name,
            "repo_allowlist": self.repo_allowlist,
            "base_url": self.base_url,
            "status": self.status,
            "has_token": self.has_token,
            "last_verified_at": self.last_verified_at,
            "last_used_at": self.last_used_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
        }
