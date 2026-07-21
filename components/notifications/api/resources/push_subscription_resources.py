"""Resource DTOs for push subscription endpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PushSubscriptionResource:
    """Output DTO for a registered push device.

    Deliberately excludes ``endpoint`` and ``keys`` — the raw endpoint URL
    grants send access, so the API echoes only the hash identity.
    """

    id: str
    platform: str
    endpoint_hash: str
    device_label: str
    status: str
    created: bool

    @classmethod
    def from_outcome(cls, outcome) -> PushSubscriptionResource:
        record = outcome.record
        return cls(
            id=record.id,
            platform=record.platform,
            endpoint_hash=record.endpoint_hash,
            device_label=record.device_label,
            status=record.status,
            created=outcome.created,
        )

    def to_dict(self) -> dict:
        return asdict(self)
