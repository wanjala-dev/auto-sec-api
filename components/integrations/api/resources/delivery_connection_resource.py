"""Resource DTO: a DeliveryConnection payload for the REST adapter (ADR 0016 D2).

**The stored credential is never returned — not even masked.** ``has_secret`` (a
boolean) is all the UI needs to know whether one is stored.

ADR 0016 D2 sketched returning a masked tail (``…/B00/••••wxyz``). That is dropped
deliberately, matching ``VcsConnectionResource``'s stricter existing rule. A Slack
incoming-webhook URL *is* the credential (the ADR's own R1 cites Slack saying so and
noting they actively hunt leaked ones), so a tail would leak live bearer-token entropy
into API responses, browser history, and any log that captures them. The masked tail
existed only to tell connections apart — ``name`` and ``channel`` already do that, and
they are not secret.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryConnectionResource:
    id: str
    kind: str
    name: str
    auth_mode: str
    channel: str
    min_severity: str
    events: list
    status: str
    is_enabled: bool
    has_secret: bool
    last_verified_at: str | None
    last_delivery_at: str | None
    last_error: str
    created_at: str | None

    @classmethod
    def from_model(cls, connection) -> DeliveryConnectionResource:
        config = connection.config or {}
        return cls(
            id=str(connection.id),
            kind=connection.kind,
            name=connection.name,
            auth_mode=connection.auth_mode,
            # Channel label is display config, not a secret.
            channel=str(config.get("channel") or ""),
            min_severity=connection.min_severity,
            events=list(connection.events or []),
            status=connection.status,
            is_enabled=connection.is_enabled,
            has_secret=bool(connection.secret_ciphertext),
            last_verified_at=connection.last_verified_at.isoformat() if connection.last_verified_at else None,
            last_delivery_at=connection.last_delivery_at.isoformat() if connection.last_delivery_at else None,
            last_error=connection.last_error or "",
            created_at=connection.created_at.isoformat() if connection.created_at else None,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "auth_mode": self.auth_mode,
            "channel": self.channel,
            "min_severity": self.min_severity,
            "events": self.events,
            "status": self.status,
            "is_enabled": self.is_enabled,
            "has_secret": self.has_secret,
            "last_verified_at": self.last_verified_at,
            "last_delivery_at": self.last_delivery_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
        }
