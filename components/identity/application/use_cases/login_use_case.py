"""Use case: Authenticate a user and issue tokens.

Orchestrates credential verification, lockout policy, audit recording,
OTP gating, and token issuance. No Django imports — depends only on ports
and domain policies.
"""

from __future__ import annotations

from components.identity.application.commands.login_command import (
    LoginCommand,
    LoginFailure,
    LoginResult,
)
from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.auth_lockout_port import AuthLockoutPort
from components.identity.application.ports.authentication_port import AuthenticationPort
from components.identity.application.ports.otp_device_port import OTPDevicePort
from components.identity.application.ports.security_notification_port import SecurityNotificationPort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_port import TokenPort
from components.identity.domain.enums import AuthEventCode
from components.identity.domain.policies.auth_lockout_policy import (
    evaluate_lockout,
    should_lock,
)
from components.identity.domain.policies.otp_verification_policy import requires_otp


class LoginUseCase:
    """Application use case for user login."""

    def __init__(
        self,
        *,
        auth_port: AuthenticationPort,
        lockout_port: AuthLockoutPort,
        audit_port: AuthAuditPort,
        token_port: TokenPort,
        otp_port: OTPDevicePort,
        notification_port: SecurityNotificationPort,
        session_registry: SessionRegistryPort,
    ) -> None:
        self._auth = auth_port
        self._lockout = lockout_port
        self._audit = audit_port
        self._tokens = token_port
        self._otp = otp_port
        self._notification = notification_port
        self._sessions = session_registry

    def execute(self, command: LoginCommand) -> LoginResult | LoginFailure:
        """Execute the login flow. Returns LoginResult on success, LoginFailure on error."""
        email = (command.email or "").strip().lower()
        password = command.password
        context = command.context

        # 1. Check lockout
        is_locked, remaining_seconds = self._lockout.is_locked(scope="login", identifier=email)
        if is_locked:
            return LoginFailure(
                reason="locked",
                message=f"Too many failed login attempts. Try again in {remaining_seconds} seconds.",
                locked=True,
                remaining_seconds=remaining_seconds,
            )

        # 2. Check auth provider mismatch
        auth_provider = self._auth.get_auth_provider(email)
        if auth_provider is not None and auth_provider != "email":
            self._audit.record_event(
                event_code=AuthEventCode.LOGIN_FAILED,
                user_id=None,
                email=email,
                success=False,
                context=context,
                metadata={"reason": "wrong_auth_provider"},
            )
            return LoginFailure(
                reason="wrong_auth_provider",
                message=f"Please continue your login using {auth_provider}",
            )

        # 3. Authenticate credentials
        user = self._auth.authenticate(email, password)
        if user is None:
            # Record failure + check lockout threshold
            failure_count = self._lockout.increment_failure(scope="login", identifier=email)
            if should_lock(failure_count):
                from components.identity.domain.enums import LOCKOUT_WINDOW_MINUTES

                self._lockout.activate_lockout(
                    scope="login",
                    identifier=email,
                    window_minutes=LOCKOUT_WINDOW_MINUTES,
                )
            lockout_status = evaluate_lockout(
                failure_count=failure_count,
                is_currently_locked=should_lock(failure_count),
                remaining_seconds=0,
            )
            self._audit.record_event(
                event_code=AuthEventCode.LOGIN_FAILED,
                user_id=None,
                email=email,
                success=False,
                context=context,
                metadata={
                    "reason": "invalid_credentials",
                    "lockout": {
                        "locked": lockout_status.locked,
                        "remaining_seconds": lockout_status.remaining_seconds,
                        "remaining_attempts": lockout_status.remaining_attempts,
                        "warn": lockout_status.warn,
                    },
                },
            )
            if lockout_status.locked:
                return LoginFailure(
                    reason="locked",
                    message=f"Too many failed login attempts. Try again in {lockout_status.remaining_seconds} seconds.",
                    locked=True,
                    remaining_seconds=lockout_status.remaining_seconds,
                )
            if lockout_status.warn:
                return LoginFailure(
                    reason="invalid_credentials",
                    message=f"Invalid credentials. {lockout_status.remaining_attempts} attempts remaining before lockout.",
                    warn=True,
                    remaining_attempts=lockout_status.remaining_attempts,
                )
            return LoginFailure(
                reason="invalid_credentials",
                message="Invalid credentials, try again",
            )

        # 4. Check user is active
        if not user.is_active:
            self._audit.record_event(
                event_code=AuthEventCode.LOGIN_FAILED,
                user_id=user.id,
                email=email,
                success=False,
                context=context,
                metadata={"reason": "inactive_user"},
            )
            return LoginFailure(reason="inactive_user", message="Account disabled, contact admin")

        # 5. Check email is verified
        if not user.is_verified:
            self._audit.record_event(
                event_code=AuthEventCode.LOGIN_FAILED,
                user_id=user.id,
                email=email,
                success=False,
                context=context,
                metadata={"reason": "email_not_verified"},
            )
            return LoginFailure(reason="email_not_verified", message="Email is not verified")

        # 6. Clear lockout on success
        self._lockout.clear(scope="login", identifier=email)

        # 7. OTP gating
        otp_required = False
        preauth_token_str: str | None = None
        tokens: dict = {}

        if requires_otp(user):
            device_info = self._otp.get_totp_device(user.id, confirmed=True)
            if device_info is None:
                device_info = self._otp.get_static_device(user.id)
            if device_info is not None:
                otp_required = True
                preauth = self._tokens.issue_preauth_token(user.id, lifetime_minutes=5)
                preauth_token_str = preauth.access
        session_jti: str | None = None
        if not otp_required:
            device_info = self._otp.get_totp_device(user.id, confirmed=True)
            device_id = device_info.device_id if device_info else None
            token_pair = self._tokens.issue_tokens(
                user.id,
                otp_verified=False,
                device_id=device_id,
                include_refresh=True,
            )
            tokens = {"access": token_pair.access}
            if token_pair.refresh:
                tokens["refresh"] = token_pair.refresh

            # Register the login session (never breaks login — the adapter
            # logs + continues on failure). Only when a refresh token was
            # actually minted; the otp_required short-circuit mints later,
            # in VerifyOTPUseCase.
            if token_pair.refresh_jti and token_pair.refresh_expires_at:
                session_jti = token_pair.refresh_jti
                self._sessions.create_session(
                    user_id=user.id,
                    refresh_jti=token_pair.refresh_jti,
                    expires_at=token_pair.refresh_expires_at,
                    context=context,
                    login_method="password",
                )

        # 8. Record success
        self._audit.record_event(
            event_code=AuthEventCode.LOGIN,
            user_id=user.id,
            email=email,
            success=True,
            context=context,
            metadata={"session_jti": session_jti} if session_jti else None,
        )
        self._notification.notify_security_event(
            actor_id=None,
            user_id=user.id,
            verb="logged in",
            event_code=AuthEventCode.LOGIN,
            metadata={"ip": context.ip_address, "user_agent": context.user_agent},
        )

        return LoginResult(
            user_id=user.id,
            email=user.email,
            username=user.username,
            is_onboard_complete=user.is_onboard_complete,
            is_contributor=user.is_contributor,
            two_factor_enabled=user.two_factor_enabled,
            two_factor_confirmed_at=user.two_factor_confirmed_at,
            otp_required=otp_required,
            preauth_token=preauth_token_str,
            tokens=tokens,
        )
