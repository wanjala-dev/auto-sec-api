"""Read the django-otp device facts a second-factor decision needs.

The *rule* lives in the domain
(``domain/policies/otp_verification_policy.second_factor_required``); this
module only supplies it with facts, because "does a confirmed TOTP device
exist?" is a database question and the domain is framework-free.

Shared by the passwordless sign-in adapters (magic link, Google) so the lookup
exists once. Both mint a session directly, so both must ask the same question
the password login asks before handing one out — a second factor that only the
password door enforces is not a second factor.
"""

from __future__ import annotations

from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from components.identity.domain.policies.otp_verification_policy import second_factor_required


def second_factor_required_for(user) -> bool:
    """True when ``user`` must present a second factor before getting a session.

    Mirrors ``LoginUseCase``'s gate exactly — armed flag AND a device that can
    actually answer the challenge (confirmed TOTP, or recovery codes).
    """
    if not getattr(user, "two_factor_enabled", False):
        return False
    return second_factor_required(
        two_factor_enabled=True,
        has_confirmed_totp_device=TOTPDevice.objects.filter(user=user, confirmed=True).exists(),
        has_static_device=StaticDevice.objects.filter(user=user).exists(),
    )
