"""Use case: Set up a new TOTP device for a user.

Creates or retrieves an unconfirmed TOTP device and returns its config URL
for QR code display. No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.identity.application.commands.otp_commands import (
    SetupOTPCommand,
    SetupOTPResult,
)
from components.identity.application.ports.otp_device_port import OTPDevicePort


class SetupOTPUseCase:
    """Application use case for OTP device setup."""

    def __init__(self, *, otp_port: OTPDevicePort) -> None:
        self._otp = otp_port

    def execute(self, command: SetupOTPCommand) -> SetupOTPResult:
        """Create or retrieve an unconfirmed TOTP device and return its config URL."""
        _device_info, config_url = self._otp.create_or_get_totp_device(command.user_id)
        return SetupOTPResult(otpauth_url=config_url)
