"""Use case: Disable 2FA by deleting all OTP devices.

No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.identity.application.commands.otp_commands import (
    DisableOTPCommand,
    DisableOTPResult,
)
from components.identity.application.ports.otp_device_port import OTPDevicePort
from components.identity.application.ports.token_port import TokenPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort


class DisableOTPUseCase:
    """Application use case for disabling 2FA."""

    def __init__(
        self,
        *,
        otp_port: OTPDevicePort,
        token_port: TokenPort,
        user_repo: UserRepositoryPort,
    ) -> None:
        self._otp = otp_port
        self._tokens = token_port
        self._user_repo = user_repo

    def execute(self, command: DisableOTPCommand) -> DisableOTPResult:
        """Delete all OTP devices and disable 2FA for the user."""
        # 1. Delete all devices
        self._otp.delete_all_devices(command.user_id)

        # 2. Disable 2FA on the user
        self._user_repo.disable_two_factor(command.user_id)

        # 3. Issue fresh tokens (no OTP claim)
        token_pair = self._tokens.issue_tokens(
            command.user_id,
            otp_verified=False,
            device_id=None,
            include_refresh=True,
        )
        tokens = {"access": token_pair.access}
        if token_pair.refresh:
            tokens["refresh"] = token_pair.refresh

        return DisableOTPResult(two_factor_enabled=False, tokens=tokens)
