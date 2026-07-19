"""Composition root for the Identity bounded context.

This provider wires concrete infrastructure adapters to application use cases.
Controllers call this provider to get fully composed use case instances.
"""

from __future__ import annotations

from components.identity.application.policies.org_audit_visibility_policy import OrgAuditVisibilityPolicy
from components.identity.application.use_cases.change_password_use_case import ChangePasswordUseCase
from components.identity.application.use_cases.check_lockout_use_case import CheckLockoutUseCase
from components.identity.application.use_cases.disable_otp_use_case import DisableOTPUseCase
from components.identity.application.use_cases.enrich_session_use_case import EnrichSessionUseCase
from components.identity.application.use_cases.get_org_audit_log_settings_use_case import (
    GetOrgAuditLogSettingsUseCase,
)
from components.identity.application.use_cases.list_login_activity_use_case import ListLoginActivityUseCase
from components.identity.application.use_cases.list_my_sessions_use_case import ListMySessionsUseCase
from components.identity.application.use_cases.list_workspace_login_activity_use_case import (
    ListWorkspaceLoginActivityUseCase,
)
from components.identity.application.use_cases.list_workspace_sessions_use_case import ListWorkspaceSessionsUseCase
from components.identity.application.use_cases.login_use_case import LoginUseCase
from components.identity.application.use_cases.logout_use_case import LogoutUseCase
from components.identity.application.use_cases.record_audit_event_use_case import RecordAuditEventUseCase
from components.identity.application.use_cases.record_auth_failure_use_case import RecordAuthFailureUseCase
from components.identity.application.use_cases.register_user_use_case import RegisterUserUseCase
from components.identity.application.use_cases.request_password_reset_use_case import RequestPasswordResetUseCase
from components.identity.application.use_cases.revoke_other_sessions_use_case import RevokeOtherSessionsUseCase
from components.identity.application.use_cases.revoke_session_use_case import RevokeSessionUseCase
from components.identity.application.use_cases.set_new_password_use_case import SetNewPasswordUseCase
from components.identity.application.use_cases.set_org_audit_log_settings_use_case import (
    SetOrgAuditLogSettingsUseCase,
)
from components.identity.application.use_cases.setup_otp_use_case import SetupOTPUseCase
from components.identity.application.use_cases.trash_workspace_login_activity_use_case import (
    TrashWorkspaceLoginActivityUseCase,
)
from components.identity.application.use_cases.verify_email_use_case import VerifyEmailUseCase
from components.identity.application.use_cases.verify_otp_use_case import VerifyOTPUseCase
from components.identity.infrastructure.adapters.cache_lockout_adapter import CacheLockoutAdapter
from components.identity.infrastructure.adapters.django_authentication_adapter import DjangoAuthenticationAdapter
from components.identity.infrastructure.adapters.django_email_verification_adapter import DjangoEmailVerificationAdapter
from components.identity.infrastructure.adapters.django_password_reset_adapter import DjangoPasswordResetAdapter
from components.identity.infrastructure.adapters.jwt_token_adapter import JWTTokenAdapter
from components.identity.infrastructure.adapters.jwt_token_revocation_adapter import JWTTokenRevocationAdapter
from components.identity.infrastructure.adapters.maxmind_geoip_adapter import MaxMindGeoIPAdapter
from components.identity.infrastructure.adapters.org_audit_log_settings_adapter import (
    WorkspacePreferenceOrgAuditLogSettingsAdapter,
)
from components.identity.infrastructure.adapters.otp_device_adapter import DjangoOTPDeviceAdapter
from components.identity.infrastructure.adapters.security_notification_adapter import DjangoSecurityNotificationAdapter
from components.identity.infrastructure.adapters.user_agents_parser_adapter import UserAgentsParserAdapter
from components.identity.infrastructure.repositories.orm_auth_audit_repository import OrmAuthAuditRepository
from components.identity.infrastructure.repositories.orm_login_activity_exclusion_repository import (
    OrmLoginActivityExclusionRepository,
)
from components.identity.infrastructure.repositories.orm_login_activity_repository import OrmLoginActivityRepository
from components.identity.infrastructure.repositories.orm_user_query_repository import OrmUserQueryRepository
from components.identity.infrastructure.repositories.orm_user_repository import OrmUserRepository
from components.identity.infrastructure.repositories.orm_user_session_repository import OrmUserSessionRepository


class IdentityProvider:
    """Composition root that builds fully-wired use case instances."""

    @staticmethod
    def build_user_repository() -> OrmUserRepository:
        return OrmUserRepository()

    @staticmethod
    def build_session_registry() -> OrmUserSessionRepository:
        return OrmUserSessionRepository()

    @staticmethod
    def build_user_query_repository() -> OrmUserQueryRepository:
        return OrmUserQueryRepository()

    @staticmethod
    def build_token_adapter() -> JWTTokenAdapter:
        return JWTTokenAdapter()

    @staticmethod
    def build_otp_adapter() -> DjangoOTPDeviceAdapter:
        return DjangoOTPDeviceAdapter()

    @staticmethod
    def build_email_verification_adapter() -> DjangoEmailVerificationAdapter:
        return DjangoEmailVerificationAdapter()

    @staticmethod
    def build_check_lockout_use_case() -> CheckLockoutUseCase:
        return CheckLockoutUseCase(lockout_port=CacheLockoutAdapter())

    @staticmethod
    def build_record_auth_failure_use_case() -> RecordAuthFailureUseCase:
        return RecordAuthFailureUseCase(lockout_port=CacheLockoutAdapter())

    @staticmethod
    def build_record_audit_event_use_case() -> RecordAuditEventUseCase:
        return RecordAuditEventUseCase(audit_port=OrmAuthAuditRepository())

    @staticmethod
    def build_logout_use_case() -> LogoutUseCase:
        return LogoutUseCase(
            token_revocation=JWTTokenRevocationAdapter(),
            audit_port=OrmAuthAuditRepository(),
            session_registry=OrmUserSessionRepository(),
        )

    @staticmethod
    def build_login_use_case() -> LoginUseCase:
        return LoginUseCase(
            auth_port=DjangoAuthenticationAdapter(),
            lockout_port=CacheLockoutAdapter(),
            audit_port=OrmAuthAuditRepository(),
            token_port=JWTTokenAdapter(),
            otp_port=DjangoOTPDeviceAdapter(),
            notification_port=DjangoSecurityNotificationAdapter(),
            session_registry=OrmUserSessionRepository(),
        )

    @staticmethod
    def build_register_user_use_case() -> RegisterUserUseCase:
        return RegisterUserUseCase(
            user_repo=OrmUserRepository(),
            token_port=JWTTokenAdapter(),
            email_port=DjangoEmailVerificationAdapter(),
        )

    @staticmethod
    def build_verify_email_use_case() -> VerifyEmailUseCase:
        return VerifyEmailUseCase(
            user_repo=OrmUserRepository(),
            token_port=JWTTokenAdapter(),
            audit_port=OrmAuthAuditRepository(),
        )

    @staticmethod
    def build_request_password_reset_use_case() -> RequestPasswordResetUseCase:
        return RequestPasswordResetUseCase(
            user_repo=OrmUserRepository(),
            reset_port=DjangoPasswordResetAdapter(),
            audit_port=OrmAuthAuditRepository(),
            notification_port=DjangoSecurityNotificationAdapter(),
        )

    @staticmethod
    def build_set_new_password_use_case() -> SetNewPasswordUseCase:
        return SetNewPasswordUseCase(
            reset_port=DjangoPasswordResetAdapter(),
            audit_port=OrmAuthAuditRepository(),
            notification_port=DjangoSecurityNotificationAdapter(),
        )

    @staticmethod
    def build_change_password_use_case() -> ChangePasswordUseCase:
        return ChangePasswordUseCase(
            user_repo=OrmUserRepository(),
            audit_port=OrmAuthAuditRepository(),
            notification_port=DjangoSecurityNotificationAdapter(),
        )

    @staticmethod
    def build_security_notification_adapter() -> DjangoSecurityNotificationAdapter:
        return DjangoSecurityNotificationAdapter()

    @staticmethod
    def build_setup_otp_use_case() -> SetupOTPUseCase:
        return SetupOTPUseCase(otp_port=DjangoOTPDeviceAdapter())

    @staticmethod
    def build_verify_otp_use_case() -> VerifyOTPUseCase:
        return VerifyOTPUseCase(
            otp_port=DjangoOTPDeviceAdapter(),
            lockout_port=CacheLockoutAdapter(),
            audit_port=OrmAuthAuditRepository(),
            token_port=JWTTokenAdapter(),
            user_repo=OrmUserRepository(),
            session_registry=OrmUserSessionRepository(),
        )

    @staticmethod
    def build_disable_otp_use_case() -> DisableOTPUseCase:
        return DisableOTPUseCase(
            otp_port=DjangoOTPDeviceAdapter(),
            token_port=JWTTokenAdapter(),
            user_repo=OrmUserRepository(),
        )

    # ── Session enrichment + self-serve session management (T2-S2/S3) ──

    @staticmethod
    def build_geoip_adapter() -> MaxMindGeoIPAdapter:
        return MaxMindGeoIPAdapter()

    @staticmethod
    def build_user_agent_parser() -> UserAgentsParserAdapter:
        return UserAgentsParserAdapter()

    @staticmethod
    def build_enrich_session_use_case() -> EnrichSessionUseCase:
        return EnrichSessionUseCase(
            session_registry=OrmUserSessionRepository(),
            user_agent_parser=IdentityProvider.build_user_agent_parser(),
            geoip=IdentityProvider.build_geoip_adapter(),
        )

    @staticmethod
    def build_list_my_sessions_use_case() -> ListMySessionsUseCase:
        return ListMySessionsUseCase(session_registry=OrmUserSessionRepository())

    @staticmethod
    def build_revoke_session_use_case() -> RevokeSessionUseCase:
        return RevokeSessionUseCase(
            session_registry=OrmUserSessionRepository(),
            token_revocation=JWTTokenRevocationAdapter(),
            audit_port=OrmAuthAuditRepository(),
        )

    @staticmethod
    def build_revoke_other_sessions_use_case() -> RevokeOtherSessionsUseCase:
        return RevokeOtherSessionsUseCase(
            session_registry=OrmUserSessionRepository(),
            token_revocation=JWTTokenRevocationAdapter(),
            audit_port=OrmAuthAuditRepository(),
        )

    @staticmethod
    def build_list_login_activity_use_case() -> ListLoginActivityUseCase:
        return ListLoginActivityUseCase(activity_port=OrmLoginActivityRepository())

    @staticmethod
    def build_org_audit_visibility_policy() -> OrgAuditVisibilityPolicy:
        return OrgAuditVisibilityPolicy(settings_port=WorkspacePreferenceOrgAuditLogSettingsAdapter())

    @staticmethod
    def build_get_org_audit_log_settings_use_case() -> GetOrgAuditLogSettingsUseCase:
        return GetOrgAuditLogSettingsUseCase(settings_port=WorkspacePreferenceOrgAuditLogSettingsAdapter())

    @staticmethod
    def build_set_org_audit_log_settings_use_case() -> SetOrgAuditLogSettingsUseCase:
        return SetOrgAuditLogSettingsUseCase(settings_port=WorkspacePreferenceOrgAuditLogSettingsAdapter())

    @staticmethod
    def build_list_workspace_login_activity_use_case() -> ListWorkspaceLoginActivityUseCase:
        return ListWorkspaceLoginActivityUseCase(
            activity_port=OrmLoginActivityRepository(),
            visibility_policy=IdentityProvider.build_org_audit_visibility_policy(),
        )

    @staticmethod
    def build_list_workspace_sessions_use_case() -> ListWorkspaceSessionsUseCase:
        return ListWorkspaceSessionsUseCase(
            activity_port=OrmLoginActivityRepository(),
            visibility_policy=IdentityProvider.build_org_audit_visibility_policy(),
        )

    @staticmethod
    def build_trash_workspace_login_activity_use_case() -> TrashWorkspaceLoginActivityUseCase:
        # Lazy import: the recycle-bin composition root registers THIS
        # context's soft-delete adapter, so a module-level import here
        # would be circular.
        from components.recycle_bin.application.providers.recycle_bin_provider import get_recycle_bin_service

        return TrashWorkspaceLoginActivityUseCase(
            activity_port=OrmLoginActivityRepository(),
            exclusion_port=OrmLoginActivityExclusionRepository(),
            recycle_bin=get_recycle_bin_service(),
            visibility_policy=IdentityProvider.build_org_audit_visibility_policy(),
        )
