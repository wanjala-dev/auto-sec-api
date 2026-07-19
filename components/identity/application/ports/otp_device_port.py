"""Port for OTP / two-factor device management.

The application layer calls this port; infrastructure provides the
django-otp adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OTPDeviceInfo:
    """Lightweight value object representing an OTP device."""

    device_id: int
    name: str
    confirmed: bool


class OTPDevicePort(ABC):
    """Secondary/driven port for OTP device operations."""

    @abstractmethod
    def get_totp_device(self, user_id: UUID, *, confirmed: bool | None = None) -> OTPDeviceInfo | None:
        """Get the user's TOTP device, optionally filtered by confirmation status."""
        ...

    @abstractmethod
    def get_static_device(self, user_id: UUID) -> OTPDeviceInfo | None:
        """Get the user's static recovery codes device."""
        ...

    @abstractmethod
    def create_totp_device(self, user_id: UUID, *, name: str = "default") -> OTPDeviceInfo:
        """Create a new TOTP device for the user."""
        ...

    @abstractmethod
    def confirm_totp_device(self, device_id: int) -> None:
        """Mark a TOTP device as confirmed."""
        ...

    @abstractmethod
    def verify_token(self, device_id: int, token: str, *, method: str = "totp") -> bool:
        """Verify a token against the given device (``method``: "totp" | "static")."""
        ...

    @abstractmethod
    def delete_device(self, device_id: int, *, method: str = "totp") -> None:
        """Delete an OTP device (``method``: "totp" | "static")."""
        ...

    @abstractmethod
    def get_totp_config_url(self, device_id: int) -> str:
        """Return the otpauth:// config URL for a TOTP device (for QR code)."""
        ...

    @abstractmethod
    def create_or_get_totp_device(self, user_id: UUID) -> tuple[OTPDeviceInfo, str]:
        """Get or create an unconfirmed TOTP device. Returns (device_info, config_url)."""
        ...

    @abstractmethod
    def delete_all_devices(self, user_id: UUID) -> None:
        """Delete all OTP devices for a user."""
        ...
