"""Concrete ``GoogleAuthPort`` — ORM + JWT backed Google sign-in.

Owns the framework-specific concerns the use case must NOT touch:
``django.db`` (transactions/IntegrityError), the ``CustomUser`` ORM,
and the SimpleJWT issuance helper. Keeping them here is what lets the
application layer stay framework-free.

Account resolution order (deliberate, security-first):

  1. by Google ``sub`` — the stable, unique Google user id. This is
     the durable key: it survives the user changing their Google
     email, and it can't be spoofed because ``sub`` comes from a
     signature-verified token.
  2. by verified email — first-ever sign-in for a user whose ``sub``
     we've never stored. Only trusted when Google asserts
     ``email_verified`` AND the matched local account is itself a
     Google account. A pre-existing email/password account is NOT
     silently taken over — the user is steered to password login.
     (Explicit, consented account-linking is a deliberate follow-up.)
  3. create — a fresh passwordless account.

There is NO shared password. Google users get
``set_unusable_password()``, so the normal password-login endpoint can
never authenticate them — closing the account-takeover hole the old
shared ``SOCIAL_SECRET`` opened.
"""

from __future__ import annotations

import logging
import uuid as _uuid

from components.identity.application.ports.google_auth_port import (
    GoogleAuthError,
    GoogleAuthPort,
    GoogleIdentity,
    VerifiedGoogleSession,
)

logger = logging.getLogger(__name__)

_GOOGLE_PROVIDER = "google"

_EMAIL_UNVERIFIED = GoogleAuthError(
    code="email_unverified",
    message=("Your Google account's email is not verified. Verify it with Google, then try again."),
    status=401,
)

_ACCOUNT_INACTIVE = GoogleAuthError(
    code="account_inactive",
    message="This account is inactive. Contact support for help.",
    status=403,
)


def _provider_conflict(existing_provider: str) -> GoogleAuthError:
    provider_label = existing_provider or "email"
    return GoogleAuthError(
        code="provider_conflict",
        message=(f"An account with this email already exists. Please continue your login using {provider_label}."),
        status=409,
    )


def _username_from(identity: GoogleIdentity) -> str:
    """Readable, collision-avoiding username (email is the auth field,
    so uniqueness here is cosmetic — used for avatars/initials)."""
    from infrastructure.persistence.users.models import CustomUser

    seed = identity.name or identity.email.split("@", 1)[0] or "member"
    base = "".join(ch for ch in seed if ch.isalnum() or ch in "._-")[:30] or "member"
    candidate = base
    suffix = 1
    while CustomUser.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base[:24]}-{suffix}"
        if suffix > 1000:
            candidate = f"member-{_uuid.uuid4().hex[:8]}"
            break
    return candidate


def _sync_profile_photo(user, picture: str, *, created_user: bool) -> None:
    """Populate the profile avatar from Google's ``picture`` claim.

    On first sign-in we set it. On later sign-ins we only *backfill* when the
    profile has no photo — we never overwrite an avatar the user uploaded
    themselves. A ``UserProfile`` always exists by the time we get here (the
    ``post_save`` signal on ``CustomUser`` creates one), but we ``get_or_create``
    defensively.
    """
    picture = (picture or "").strip()
    if not picture:
        return
    from infrastructure.persistence.users.models import UserProfile

    profile, _ = UserProfile.objects.get_or_create(user=user)
    has_photo = bool((profile.photo_url or "").strip())
    if (created_user or not has_photo) and profile.photo_url != picture:
        profile.photo_url = picture
        profile.save(update_fields=["photo_url"])


class OrmGoogleAuthAdapter(GoogleAuthPort):
    """Production adapter — ORM-backed, JWT-issuing, passwordless."""

    def authenticate(
        self,
        *,
        identity: GoogleIdentity,
        request_ip: str | None = None,
    ) -> VerifiedGoogleSession | GoogleAuthError:
        from django.db import IntegrityError

        from infrastructure.persistence.users.models import CustomUser

        # 1) Link by stable Google sub.
        user = CustomUser.objects.filter(google_sub=identity.sub).first()

        # 2) Fall back to verified email — first sign-in for this sub.
        if user is None:
            existing = CustomUser.objects.filter(email__iexact=identity.email).first()
            if existing is not None:
                if not identity.email_verified:
                    logger.info(
                        "google_auth_unverified_email_match email=%s",
                        identity.email,
                    )
                    return _EMAIL_UNVERIFIED
                if existing.auth_provider != _GOOGLE_PROVIDER:
                    logger.info(
                        "google_auth_provider_conflict email=%s provider=%s",
                        identity.email,
                        existing.auth_provider,
                    )
                    return _provider_conflict(existing.auth_provider)
                # Same person, Google account we simply hadn't stamped
                # with their sub yet — backfill it.
                user = existing
                user.google_sub = identity.sub
                user.save(update_fields=["google_sub"])

        created_user = False
        # 3) Create a fresh passwordless account.
        if user is None:
            if not identity.email_verified:
                return _EMAIL_UNVERIFIED
            try:
                user = CustomUser.objects.create(
                    email=identity.email,
                    username=_username_from(identity),
                    is_active=True,
                    is_verified=True,
                    auth_provider=_GOOGLE_PROVIDER,
                    google_sub=identity.sub,
                )
                user.set_unusable_password()
                user.save(update_fields=["password"])
                created_user = True
                logger.info(
                    "google_auth_created_user email=%s user_id=%s",
                    identity.email,
                    user.id,
                )
            except IntegrityError:
                # Race: a parallel sign-in created the same account.
                # Re-read by sub then email and proceed.
                user = (
                    CustomUser.objects.filter(google_sub=identity.sub).first()
                    or CustomUser.objects.filter(email__iexact=identity.email).first()
                )
                if user is None:
                    logger.exception(
                        "google_auth_create_race_unresolved email=%s",
                        identity.email,
                    )
                    return GoogleAuthError(
                        code="create_failed",
                        message="Unable to complete sign-in. Please try again.",
                        status=500,
                    )

        if not user.is_active:
            return _ACCOUNT_INACTIVE

        # A user who proves Google email ownership is verified.
        if not user.is_verified and identity.email_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified"])

        # Avatar from Google — set on signup, backfill later only if empty.
        _sync_profile_photo(user, identity.picture, created_user=created_user)

        from components.identity.infrastructure.adapters.user_utils import (
            issue_tokens,
        )

        tokens = issue_tokens(user, otp_verified=False, device=None, include_refresh=True)
        logger.info(
            "google_auth_ok email=%s user_id=%s created_user=%s",
            user.email,
            user.id,
            created_user,
        )
        return VerifiedGoogleSession(
            user_id=str(user.id),
            email=user.email,
            username=user.username,
            is_onboard_complete=bool(getattr(user, "is_onboard_complete", False)),
            is_contributor=bool(getattr(user, "is_contributor", False)),
            access_token=tokens.get("access") or "",
            refresh_token=tokens.get("refresh") or "",
            created_user=created_user,
            refresh_jti=tokens.get("refresh_jti"),
            refresh_expires_at=tokens.get("refresh_expires_at"),
        )
