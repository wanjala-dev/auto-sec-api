import threading
from datetime import UTC, datetime, timedelta

from django.core.mail import EmailMessage
from django.utils import timezone
from django_otp import devices_for_user
from django_otp.models import Device
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


class EmailThread(threading.Thread):
    def __init__(self, email):
        self.email = email
        threading.Thread.__init__(self)

    def run(self):
        self.email.send()


class Util:
    @staticmethod
    def send_email(data):
        email = EmailMessage(subject=data["email_subject"], body=data["email_body"], to=[data["to_email"]])
        EmailThread(email).start()


"""
OTP
"""


def jwt_otp_payload(user, device=None):
    """
    Optionally include OTP device in JWT payload.
    Returns the claims dict for compatibility with callers that inspect the payload.
    """
    token = _build_access_token(user, device=device, otp_verified=device is not None)
    return token.payload


def get_custom_jwt(user, device):
    """
    Helper to generate a JWT for a validated OTP device.
    This resets the orig_iat timestamp, as we've re-validated the user.
    """
    token = _build_access_token(user, device=device, otp_verified=device is not None)
    return str(token)


def otp_is_verified(self, request):
    """
    Helper to determine if user has verified OTP.
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "two_factor_enabled", False):
        return True

    auth = JWTAuthentication()
    try:
        header = auth.get_header(request)
        if header is None:
            return False
        raw_token = auth.get_raw_token(header)
        if raw_token is None:
            return False
        validated_token = auth.get_validated_token(raw_token)
    except Exception:
        return False

    if validated_token.get("otp_pending"):
        return False
    if not validated_token.get("otp_verified", False):
        return False

    persistent_id = validated_token.get("otp_device_id")
    if not persistent_id:
        return False

    try:
        device = Device.from_persistent_id(persistent_id)
    except Exception:
        return False

    if device is None:
        return False
    if getattr(device, "user_id", None) != request.user.id:
        return False
    if getattr(device, "confirmed", True) is False:
        return False
    return True


def _build_access_token(user, device=None, *, otp_verified=False) -> AccessToken:
    token = AccessToken.for_user(user)
    username = getattr(user, getattr(user, "USERNAME_FIELD", "username"), "")
    token["username"] = username
    token["user_id"] = user.id
    token["otp_verified"] = bool(otp_verified)
    device_verified = (
        otp_verified
        and device is not None
        and getattr(device, "user_id", None) == user.id
        and getattr(device, "confirmed", True)
    )
    token["otp_device_id"] = device.persistent_id if device_verified else None
    return token


def issue_tokens(user, *, otp_verified=False, device=None, include_refresh=True):
    """
    Issue SimpleJWT tokens with OTP claims attached.

    When a refresh token is issued, both tokens carry a ``sid`` claim equal
    to the refresh token's ``jti`` — the stable session identifier for the
    ``UserSession`` registry (refresh-token rotation is OFF everywhere, so
    the jti never changes for a login's lifetime). The returned dict also
    exposes ``refresh_jti`` and ``refresh_expires_at`` (tz-aware datetime)
    so callers can register the session.
    """

    def _add_claims(token):
        token["otp_verified"] = bool(otp_verified)
        device_verified = (
            otp_verified
            and device is not None
            and getattr(device, "user_id", None) == user.id
            and getattr(device, "confirmed", True)
        )
        token["otp_device_id"] = device.persistent_id if device_verified else None
        return token

    if include_refresh:
        refresh = _add_claims(RefreshToken.for_user(user))
        refresh_jti = str(refresh["jti"])
        refresh["sid"] = refresh_jti
        access = _add_claims(refresh.access_token)
        access["sid"] = refresh_jti
        refresh_expires_at = datetime.fromtimestamp(refresh["exp"], tz=UTC)
        return {
            "refresh": str(refresh),
            "access": str(access),
            "refresh_jti": refresh_jti,
            "refresh_expires_at": refresh_expires_at,
        }

    access = _add_claims(AccessToken.for_user(user))
    return {
        "refresh": None,
        "access": str(access),
        "refresh_jti": None,
        "refresh_expires_at": None,
    }


def issue_preauth_token(user, lifetime_minutes=10) -> str:
    """
    Issue a short-lived access token used only for completing OTP verification.
    """
    token = AccessToken.for_user(user)
    token.set_exp(from_time=timezone.now(), lifetime=timedelta(minutes=lifetime_minutes))
    token["otp_verified"] = False
    token["otp_pending"] = True
    return str(token)


def get_user_totp_device(user, confirmed=None):
    devices = devices_for_user(user, confirmed=confirmed)
    for device in devices:
        if isinstance(device, TOTPDevice):
            return device
    return None


def get_user_static_device(user):
    devices = devices_for_user(user, confirmed=None)
    for device in devices:
        if isinstance(device, StaticDevice):
            return device
    return None


"""
OTP
"""
