"""Request DTOs for push subscription endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegisterPushSubscriptionRequest:
    """Input DTO for POST /notifications/push/subscriptions/."""

    endpoint: str
    keys: dict[str, Any] = field(default_factory=dict)
    device_label: str = ""
    platform: str = "web"

    @classmethod
    def from_request(cls, request) -> RegisterPushSubscriptionRequest:
        data = request.data or {}
        return cls(
            endpoint=str(data.get("endpoint") or ""),
            keys=data.get("keys") or {},
            device_label=str(data.get("device_label") or ""),
            platform=str(data.get("platform") or "web"),
        )


@dataclass(frozen=True)
class RevokePushSubscriptionRequest:
    """Input DTO for DELETE /notifications/push/subscriptions/ — accepts
    either the raw endpoint or its sha256 hex hash."""

    endpoint: str = ""
    endpoint_hash: str = ""

    @classmethod
    def from_request(cls, request) -> RevokePushSubscriptionRequest:
        data = request.data or {}
        return cls(
            endpoint=str(data.get("endpoint") or ""),
            endpoint_hash=str(data.get("endpoint_hash") or ""),
        )
