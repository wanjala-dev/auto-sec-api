"""Entropy-based password validator using zxcvbn.

Registered in ``AUTH_PASSWORD_VALIDATORS``. Rejects passwords whose zxcvbn
score falls below ``PASSWORD_MINIMAL_STRENGTH`` (0-4). Default threshold is
3 — "strong enough to resist online attacks."
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


_DEFAULT_MIN_SCORE = 3


class ZxcvbnPasswordValidator:
    """zxcvbn-backed password strength validator."""

    def __init__(self, min_score: int | None = None) -> None:
        self.min_score = (
            min_score
            if min_score is not None
            else getattr(settings, "PASSWORD_MINIMAL_STRENGTH", _DEFAULT_MIN_SCORE)
        )

    def validate(self, password: str, user=None) -> None:
        from zxcvbn import zxcvbn

        user_inputs: list[str] = []
        if user is not None:
            for attr in ("email", "username", "first_name", "last_name"):
                value = getattr(user, attr, None)
                if value:
                    user_inputs.append(str(value))

        # zxcvbn is slow on long inputs; truncate to 72 (bcrypt's effective max)
        # to cap worst-case work per validation.
        result = zxcvbn(password[:72], user_inputs=user_inputs)
        score = int(result.get("score", 0))
        if score >= self.min_score:
            return

        feedback = result.get("feedback") or {}
        suggestions = feedback.get("suggestions") or []
        warning = feedback.get("warning") or ""
        hint = " ".join(filter(None, [warning, *suggestions])) or _(
            "Password is too easy to guess."
        )
        raise ValidationError(hint, code="password_too_weak")

    def get_help_text(self) -> str:
        return _(
            "Your password must be strong enough to resist common attacks. "
            "Avoid dictionary words, sequences, and personal information."
        )
