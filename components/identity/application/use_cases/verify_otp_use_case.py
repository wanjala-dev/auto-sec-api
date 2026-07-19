"""Use case: Verify an OTP token (TOTP or static recovery code).

Orchestrates lockout check, token verification, device confirmation,
2FA state update, audit recording, and token issuance. Handles both
TOTP and static code verification via the ``method`` field.

No Django imports — depends only on ports and domain policies.
"""

from __future__ import annotations

from components.identity.application.commands.otp_commands import (
    VerifyOTPCommand,
    VerifyOTPFailure,
    VerifyOTPResult,
)
from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.auth_lockout_port import AuthLockoutPort
from components.identity.application.ports.otp_device_port import OTPDevicePort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_port import TokenPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort
from components.identity.domain.enums import AuthEventCode
from components.identity.domain.policies.auth_lockout_policy import should_lock


class VerifyOTPUseCase:
    """Application use case for OTP verification (TOTP + static)."""

    def __init__(
        self,
        *,
        otp_port: OTPDevicePort,
        lockout_port: AuthLockoutPort,
        audit_port: AuthAuditPort,
        token_port: TokenPort,
        user_repo: UserRepositoryPort,
        session_registry: SessionRegistryPort,
    ) -> None:
        self._otp = otp_port
        self._lockout = lockout_port
        self._audit = audit_port
        self._tokens = token_port
        self._user_repo = user_repo
        self._sessions = session_registry

    def execute(self, command: VerifyOTPCommand) -> VerifyOTPResult | VerifyOTPFailure:
        """Execute the OTP verification flow."""
        user_id = command.user_id
        lock_scope = f"otp_{command.method}_verify" if command.method == "static" else "otp_verify"
        lock_id = str(user_id)

        # 1. Check lockout
        is_locked, remaining_seconds = self._lockout.is_locked(scope=lock_scope, identifier=lock_id)
        if is_locked:
            return VerifyOTPFailure(
                reason="locked",
                message=f"Too many failed attempts. Try again in {remaining_seconds} seconds.",
                locked=True,
                remaining_seconds=remaining_seconds,
            )

        # 2. Get the appropriate device
        if command.method == "static":
            device_info = self._otp.get_static_device(user_id)
        else:
            device_info = self._otp.get_totp_device(user_id)

        # 3. Verify token (pass the method so the adapter hits the concrete
        # StaticDevice/TOTPDevice class, not the abstract Device base)
        if device_info and self._otp.verify_token(device_info.device_id, command.token, method=command.method):
            # Success path
            self._lockout.clear(scope=lock_scope, identifier=lock_id)

            # Confirm device if not yet confirmed (TOTP first-time setup)
            if command.method == "totp" and not device_info.confirmed:
                self._otp.confirm_totp_device(device_info.device_id)

            # Enable 2FA on the user
            self._user_repo.enable_two_factor(user_id)

            # Issue tokens
            token_pair = self._tokens.issue_tokens(
                user_id,
                otp_verified=True,
                device_id=device_info.device_id,
                include_refresh=True,
            )
            tokens = {"access": token_pair.access}
            if token_pair.refresh:
                tokens["refresh"] = token_pair.refresh

            # Register the login session for the freshly minted refresh
            # token (2FA logins mint here, not in LoginUseCase). Never
            # breaks verification — the adapter logs + continues.
            session_jti: str | None = None
            if token_pair.refresh_jti and token_pair.refresh_expires_at:
                session_jti = token_pair.refresh_jti
                self._sessions.create_session(
                    user_id=user_id,
                    refresh_jti=token_pair.refresh_jti,
                    expires_at=token_pair.refresh_expires_at,
                    context=command.context,
                    login_method="otp",
                )

            # Record audit success
            audit_metadata: dict = {"method": command.method}
            if session_jti:
                audit_metadata["session_jti"] = session_jti
            self._audit.record_event(
                event_code=AuthEventCode.OTP_VERIFY,
                user_id=user_id,
                email=command.email,
                success=True,
                context=command.context,
                metadata=audit_metadata,
            )

            return VerifyOTPResult(otp_verified=True, tokens=tokens)

        # 4. Failure path — record failure + check lockout
        failure_count = self._lockout.increment_failure(scope=lock_scope, identifier=lock_id)
        if should_lock(failure_count):
            from components.identity.domain.enums import LOCKOUT_WINDOW_MINUTES

            self._lockout.activate_lockout(
                scope=lock_scope,
                identifier=lock_id,
                window_minutes=LOCKOUT_WINDOW_MINUTES,
            )

        self._audit.record_event(
            event_code=AuthEventCode.OTP_VERIFY_FAILED,
            user_id=user_id,
            email=command.email,
            success=False,
            context=command.context,
            metadata={
                "method": command.method,
                "lockout": {"locked": should_lock(failure_count)},
            },
        )

        if should_lock(failure_count):
            return VerifyOTPFailure(
                reason="locked",
                message="Too many failed attempts. Try again later.",
                locked=True,
            )

        return VerifyOTPFailure(
            reason="invalid_token",
            message="Invalid token",
        )
