"""Request DTOs for the identity bounded context.

These frozen dataclasses define the shape of incoming request bodies
for identity endpoints (registration, login, password reset, OTP, etc.).
"""

from .register_user_request import RegisterUserRequest
from .login_request import LoginRequest
from .request_password_reset_request import RequestPasswordResetRequest
from .set_new_password_request import SetNewPasswordRequest
from .logout_request import LogoutRequest
from .change_password_request import ChangePasswordRequest
from .user_patch_request import UserPatchRequest
from .profile_edit_request import ProfileEditRequest
from .totp_verify_request import TOTPVerifyRequest
from .static_verify_request import StaticVerifyRequest
from .password_confirm_request import PasswordConfirmRequest
from .google_social_auth_request import GoogleSocialAuthRequest

__all__ = [
    "RegisterUserRequest",
    "LoginRequest",
    "RequestPasswordResetRequest",
    "SetNewPasswordRequest",
    "LogoutRequest",
    "ChangePasswordRequest",
    "UserPatchRequest",
    "ProfileEditRequest",
    "TOTPVerifyRequest",
    "StaticVerifyRequest",
    "PasswordConfirmRequest",
    "GoogleSocialAuthRequest",
]
