from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class LogoutRequest:
    """Input DTO for POST /logout/ endpoint.

    Used to logout and optionally revoke tokens on all devices.
    """
    refresh: str
    all_devices: bool | None = None
