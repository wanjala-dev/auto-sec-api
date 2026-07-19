"""Application service for the identity bounded context.

Orchestration only – delegates to use cases via IdentityProvider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from components.identity.application.providers.identity_provider import IdentityProvider
from components.identity.application.providers.user_context_provider import UserContextProvider
from components.identity.application.ports.user_query_port import UserQueryPort


@dataclass
class IdentityService:
    """Application service for the identity bounded context.

    Orchestration only – delegates to use cases for business logic.
    """
    identity_provider: IdentityProvider = field(default_factory=IdentityProvider)
    user_context_provider: UserContextProvider = field(default_factory=UserContextProvider)
    user_query_port: UserQueryPort = field(default_factory=lambda: IdentityProvider.build_user_query_repository())

    def register_user(self, command) -> Any:
        """Register a new user."""
        use_case = self.identity_provider.build_register_user_use_case()
        return use_case.execute(command)

    def login(self, command) -> Any:
        """Log in a user."""
        use_case = self.identity_provider.build_login_use_case()
        return use_case.execute(command)

    def logout(self, command) -> Any:
        """Log out a user."""
        use_case = self.identity_provider.build_logout_use_case()
        return use_case.execute(command)

    def verify_email(self, command) -> Any:
        """Verify user email."""
        use_case = self.identity_provider.build_verify_email_use_case()
        return use_case.execute(command)

    def change_password(self, command) -> Any:
        """Change user password."""
        use_case = self.identity_provider.build_change_password_use_case()
        return use_case.execute(command)

    def request_password_reset(self, command) -> Any:
        """Request password reset."""
        use_case = self.identity_provider.build_request_password_reset_use_case()
        return use_case.execute(command)

    def set_new_password(self, command) -> Any:
        """Set new password after reset."""
        use_case = self.identity_provider.build_set_new_password_use_case()
        return use_case.execute(command)

    def setup_otp(self, command) -> Any:
        """Set up OTP for user."""
        use_case = self.identity_provider.build_setup_otp_use_case()
        return use_case.execute(command)

    def verify_otp(self, command) -> Any:
        """Verify OTP token."""
        use_case = self.identity_provider.build_verify_otp_use_case()
        return use_case.execute(command)

    def disable_otp(self, command) -> Any:
        """Disable OTP for user."""
        use_case = self.identity_provider.build_disable_otp_use_case()
        return use_case.execute(command)

    def check_lockout(self, command) -> Any:
        """Check account lockout status."""
        use_case = self.identity_provider.build_check_lockout_use_case()
        return use_case.execute(command)

    def record_auth_failure(self, command) -> Any:
        """Record authentication failure."""
        use_case = self.identity_provider.build_record_auth_failure_use_case()
        return use_case.execute(command)

    def record_audit_event(self, command) -> Any:
        """Record audit event."""
        use_case = self.identity_provider.build_record_audit_event_use_case()
        return use_case.execute(command)

    def send_verification_email(self, **kwargs) -> bool:
        """Send verification email to user."""
        adapter = self.identity_provider.build_email_verification_adapter()
        return adapter.send_verification_email(**kwargs)

    def notify_security_event(self, **kwargs) -> Any:
        """Dispatch a security-event notification."""
        adapter = self.identity_provider.build_security_notification_adapter()
        return adapter.notify_security_event(**kwargs)

    def build_org_onboarding_payload(self, user_id=None, *, include_workspace_ids=True) -> Any:
        """Return membership gate data for org onboarding."""
        query = self.user_context_provider.build_org_onboarding_query()
        return query.execute(user_id=user_id, include_workspace_ids=include_workspace_ids)

    def build_user_context(self, user_id) -> Any:
        """Build user context with workspace and team information."""
        query = self.user_context_provider.build_user_context_query()
        return query.execute(user_id=user_id)

    def get_workspace(self, workspace_id) -> Any:
        """Get workspace details by ID.

        Delegates to the user repository to fetch workspace info.
        """
        repository = self.identity_provider.build_user_repository()
        return repository.get_workspace(workspace_id=workspace_id)

    def ensure_workspace_follower(self, workspace_id, user_id) -> None:
        """Ensure user follows the given workspace.

        Delegates to the user repository.
        """
        repository = self.identity_provider.build_user_repository()
        return repository.ensure_workspace_follower(workspace_id=workspace_id, user_id=user_id)

    # ── Query helpers for controller ─────────────────────────────────────

    def get_user_by_id(self, user_id, *, with_profile: bool = False) -> Any:
        """Get user by ID, optionally with profile pre-fetched."""
        return self.user_query_port.get_by_id(user_id, with_profile=with_profile)

    def get_user_by_email(self, email: str) -> Any:
        """Get user by email."""
        return self.user_query_port.get_by_email(email)

    def find_user_by_email_and_username(self, email: str, username: str) -> Any:
        """Find users matching email and username."""
        return self.user_query_port.find_by_email_and_username(email, username)

    def get_user_queryset(self):
        """Return the base user queryset with profile pre-fetched."""
        return self.user_query_port.get_queryset()

    def get_user_profile(self, user_id) -> Any:
        """Get user profile by user ID."""
        return self.user_query_port.get_profile(user_id)

    def list_pending_invitations(self, email: str) -> Any:
        """List pending invitations for an email."""
        return self.user_query_port.list_pending_invitations(email)

    def get_system_actor(self) -> Any:
        """Get system actor (superuser or staff) for audit events."""
        return self.user_query_port.get_system_actor()
