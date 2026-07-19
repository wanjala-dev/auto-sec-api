"""Concrete adapter for ``MagicLinkPort`` backed by Django ORM + JWT.

Owns all the framework-specific concerns the use cases must NOT touch:
``django.db.transaction``, ``django.utils.timezone``, the
``MagicLinkToken`` ORM, the ``CustomUser`` ORM, and the SimpleJWT
token-issuance helper. Keeping these here is what lets the application
layer stay framework-free.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from components.identity.application.ports.magic_link_port import (
    MagicLinkPort,
    MintedMagicLinkToken,
    VerifiedMagicLinkSession,
)

logger = logging.getLogger(__name__)


def _username_from_email(email: str) -> str:
    """Best-effort sane default username for a magic-link-created user.

    The model accepts duplicate usernames since email is the auth
    field, but readable usernames are nice for avatars / initials.
    Falls back to a UUID-suffixed donor handle on absurd collision.
    """
    from infrastructure.persistence.users.models import CustomUser

    local = email.split("@", 1)[0] or "donor"
    base = "".join(ch for ch in local if ch.isalnum() or ch in "._-")[:30] or "donor"
    candidate = base
    suffix = 1
    while CustomUser.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base[:24]}-{suffix}"
        if suffix > 1000:
            import uuid as _uuid

            candidate = f"donor-{_uuid.uuid4().hex[:8]}"
            break
    return candidate


class OrmMagicLinkAdapter(MagicLinkPort):
    """Production adapter — ORM-backed, JWT-issuing."""

    def mint_token(
        self,
        *,
        email: str,
        next_url: str,
        ttl_minutes: int,
    ) -> MintedMagicLinkToken | None:
        from django.utils import timezone

        from infrastructure.persistence.users.models import (
            CustomUser,
            MagicLinkToken,
        )

        normalized = (email or "").strip().lower()
        if not normalized:
            return None
        token_value = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(minutes=ttl_minutes)
        existing_user = CustomUser.objects.filter(email__iexact=normalized).first()
        MagicLinkToken.objects.create(
            token=token_value,
            email=normalized,
            user=existing_user,
            next_url=next_url or "",
            expires_at=expires_at,
        )
        logger.info(
            "magic_link_token_minted email=%s expires_at=%s next_url=%s",
            normalized,
            expires_at.isoformat(),
            next_url or "(none)",
        )
        return MintedMagicLinkToken(
            email=normalized,
            token=token_value,
            next_url=next_url or "",
            ttl_minutes=ttl_minutes,
        )

    def consume_token(
        self,
        *,
        token_value: str,
        request_ip: str | None,
    ) -> VerifiedMagicLinkSession | None:
        from django.db import IntegrityError
        from django.utils import timezone

        from components.identity.infrastructure.adapters.user_utils import (
            issue_tokens,
        )
        from infrastructure.persistence.users.models import (
            CustomUser,
            MagicLinkToken,
        )

        if not token_value:
            return None

        # Race-safe consumption via a single conditional UPDATE: the
        # WHERE clause carries the "still valid" predicate, so two
        # simultaneous clicks see one winner (updated_count=1) and
        # one loser (updated_count=0). The loser is treated identically
        # to an expired token. This is preferred over SELECT FOR
        # UPDATE here because that requires an enclosing transaction,
        # which the prod autocommit DB cursor on this branch does NOT
        # establish automatically. Conditional UPDATE is atomic on
        # every backend without depending on connection state — and
        # it was the source of the prod 500 right after this PR
        # deployed.
        now = timezone.now()
        updated_count = MagicLinkToken.objects.filter(
            token=token_value,
            consumed_at__isnull=True,
            expires_at__gt=now,
        ).update(consumed_at=now, consumed_by_ip=request_ip)
        if updated_count == 0:
            logger.info(
                "magic_link_verify_miss token_present=%s",
                bool(token_value),
            )
            return None
        token_row = MagicLinkToken.objects.get(token=token_value)

        user = token_row.user or CustomUser.objects.filter(email__iexact=token_row.email).first()
        created_user = False
        if user is None:
            try:
                user = CustomUser.objects.create(
                    email=token_row.email,
                    username=_username_from_email(token_row.email),
                    is_active=True,
                    is_verified=True,
                )
                user.set_unusable_password()
                user.save(update_fields=["password"])
                created_user = True
                logger.info(
                    "magic_link_created_user email=%s user_id=%s",
                    token_row.email,
                    user.id,
                )
            except IntegrityError:
                # Race: a parallel verify just created the same user.
                # Re-read and proceed as if we'd seen them all along.
                user = CustomUser.objects.filter(email__iexact=token_row.email).first()
                if user is None:
                    # Genuinely failed (rare) — clear the consumed
                    # marker so the donor can re-issue rather than
                    # burning the link they have.
                    MagicLinkToken.objects.filter(pk=token_row.pk).update(
                        consumed_at=None,
                        consumed_by_ip=None,
                    )
                    logger.exception(
                        "magic_link_user_create_race_unresolved email=%s",
                        token_row.email,
                    )
                    return None
        elif not user.is_verified:
            # Clicking the link is by definition email-ownership
            # proof — flip is_verified so downstream flows that
            # gate on it (e.g. workspace creation) don't bounce.
            user.is_verified = True
            user.save(update_fields=["is_verified"])

        # Back-link the user FK on the consumed row.
        MagicLinkToken.objects.filter(pk=token_row.pk).update(user=user)
        token_row.user = user

        tokens = issue_tokens(
            user,
            otp_verified=False,
            device=None,
            include_refresh=True,
        )
        logger.info(
            "magic_link_verify_ok email=%s user_id=%s created_user=%s",
            user.email,
            user.id,
            created_user,
        )
        return VerifiedMagicLinkSession(
            user_id=str(user.id),
            email=user.email,
            username=user.username,
            is_onboard_complete=bool(getattr(user, "is_onboard_complete", False)),
            is_contributor=bool(getattr(user, "is_contributor", False)),
            access_token=tokens.get("access") or "",
            refresh_token=tokens.get("refresh") or "",
            next_url=token_row.next_url or "",
            created_user=created_user,
            refresh_jti=tokens.get("refresh_jti"),
            refresh_expires_at=tokens.get("refresh_expires_at"),
        )
