"""Resource DTOs for the identity bounded context.

These frozen dataclasses define the shape of outgoing response payloads
for identity endpoints (user details, auth tokens, OTP setup, etc.).
"""

from .user_resource import (
    UserResource,
    UserProfileResource,
    UserDetailResource,
    UserSummaryResource,
)
from .auth_resource import (
    TokenPairResource,
    RegisterUserResource,
    LoginResource,
    EmailVerificationResource,
    PasswordResetRequestResource,
    SetNewPasswordResource,
    ChangePasswordResource,
)
from .otp_resource import (
    OTPSetupResource,
    OTPVerifyResource,
    StaticRecoveryCodesResource,
    OTPDisableResource,
)
from .workspace_resource import (
    WorkspaceResource,
    WorkspaceListResource,
    TeamResource,
    UserWithWorkspacesResource,
)

__all__ = [
    # User resources
    "UserResource",
    "UserProfileResource",
    "UserDetailResource",
    "UserSummaryResource",
    # Auth resources
    "TokenPairResource",
    "RegisterUserResource",
    "LoginResource",
    "EmailVerificationResource",
    "PasswordResetRequestResource",
    "SetNewPasswordResource",
    "ChangePasswordResource",
    # OTP resources
    "OTPSetupResource",
    "OTPVerifyResource",
    "StaticRecoveryCodesResource",
    "OTPDisableResource",
    # Workspace resources
    "WorkspaceResource",
    "WorkspaceListResource",
    "TeamResource",
    "UserWithWorkspacesResource",
]
