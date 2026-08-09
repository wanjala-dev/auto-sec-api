"""Resource DTO: a VercelConnection payload for the REST adapter (ADR 0021 D2).

The token is NEVER exposed — only ``has_token`` (a boolean) tells the UI whether a
secret is stored. ``token_expires_at`` powers the expiry nag (we ask for an
expiring token, so we must warn before it lapses).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VercelConnectionResource:
    id: str
    name: str
    team_id: str
    team_slug: str
    team_name: str
    credential_kind: str
    status: str
    has_token: bool
    token_expires_at: str | None
    last_verified_at: str | None
    last_error: str
    created_at: str | None

    @classmethod
    def from_model(cls, connection) -> VercelConnectionResource:
        return cls(
            id=str(connection.id),
            name=connection.name,
            team_id=connection.team_id or "",
            team_slug=connection.team_slug or "",
            team_name=connection.team_name or "",
            credential_kind=connection.credential_kind,
            status=connection.status,
            has_token=bool(connection.token_ciphertext),
            token_expires_at=(connection.token_expires_at.isoformat() if connection.token_expires_at else None),
            last_verified_at=(connection.last_verified_at.isoformat() if connection.last_verified_at else None),
            last_error=connection.last_error,
            created_at=(connection.created_at.isoformat() if connection.created_at else None),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "team_id": self.team_id,
            "team_slug": self.team_slug,
            "team_name": self.team_name,
            "credential_kind": self.credential_kind,
            "status": self.status,
            "has_token": self.has_token,
            "token_expires_at": self.token_expires_at,
            "last_verified_at": self.last_verified_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
        }
