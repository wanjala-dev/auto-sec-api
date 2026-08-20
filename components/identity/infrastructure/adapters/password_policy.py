"""Password strength policy — the ONE reusable enforcement of
``AUTH_PASSWORD_VALIDATORS`` across every entry point that writes a password.

Django's configured policy (min length, common-password, numeric,
user-attribute similarity, and the project's zxcvbn strength validator) was
historically only enforced on the change-password path
(``UserRepositoryPort.validate_new_password``, which requires a *persisted*
``user_id``). Register, signupapi, and password-reset-complete accepted
anything past a serializer ``min_length`` weaker than the policy itself — a
top-10 common password, an all-numeric password, or (signupapi) a
single-character password.

This module centralises the check so a brand-new user (no persisted row yet)
is validated the same way an existing one is. Pass an (unsaved) ``user`` when
you have the email/username so the user-attribute-similarity and zxcvbn
personal-info penalties still apply; ``user=None`` degrades gracefully to the
non-personalised validators.

Returns the list of human-readable failure messages (empty ⇒ the password is
acceptable), mirroring ``UserRepositoryPort.validate_new_password`` so callers
handle both the same way.
"""

from __future__ import annotations


def validate_password_strength(password: str, *, user=None) -> list[str]:
    """Run the configured password policy; return failure messages (empty ⇒ ok)."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    try:
        validate_password(password, user=user)
        return []
    except ValidationError as exc:
        return list(exc.messages)
