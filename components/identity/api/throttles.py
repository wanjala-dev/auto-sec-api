"""DRF throttle classes for identity endpoints.

Combines authentication throttles (login, password reset, email verify) and
OTP-specific throttles (TOTP verify, static recovery codes) in one place.
These are framework-specific (DRF) concerns, not business logic.
"""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _ScopedIdentityThrottle(SimpleRateThrottle):
    """Base throttle that prefers user/email identity, then falls back to client IP.

    ⚠ This is an IDENTITY throttle, NOT an IP ceiling. Its ``ip:`` branch only
    runs when the request carries no email — and whether an email is present is
    entirely up to the CALLER (it is read from the request body *or* the query
    string). An attacker therefore chooses their own bucket key: rotate the
    email and every request lands in a fresh bucket; append ``?email=<random>``
    to an endpoint that never meant to take one and the ``ip:`` fallback
    disappears too.

    So a subclass of this class NEVER constitutes a per-IP limit. Any
    anonymous-reachable view using one MUST also stack an ``_ScopedIPThrottle``
    (see below). ``tests/architecture/test_auth_throttle_ip_ceiling.py``
    enforces exactly that.
    """

    def _identity(self, request) -> str:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return f"user:{getattr(user, 'pk', user.id)}"

        email = None
        data = getattr(request, "data", None)
        if isinstance(data, dict):
            email = data.get("email")
        if not email:
            email = request.query_params.get("email")
        if email:
            return f"email:{str(email).strip().lower()}"

        return f"ip:{self.get_ident(request)}"

    def get_cache_key(self, request, view):
        ident = self._identity(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class _ScopedPrincipalThrottle(SimpleRateThrottle):
    """Base throttle keyed to authenticated user or client IP.

    Used only on views that require authentication, so in practice the bucket
    is always the principal — DRF runs ``check_permissions`` before
    ``check_throttles``, so an anonymous caller is rejected before the IP
    branch is ever reached.
    """

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            ident = str(getattr(user, "pk", user.id))
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class _ScopedIPThrottle(SimpleRateThrottle):
    """Base throttle keyed ONLY on the trusted client IP.

    The counterpart to ``_ScopedIdentityThrottle``: nothing in the request
    body or query string can influence the bucket. The IP comes from DRF's
    ``get_ident()``, which is sound because ``NUM_PROXIES`` is set (#310) —
    it reads the hop our own gateway appended, not the caller's prefix.

    Stacked ALONGSIDE an identity throttle, never instead of one. The identity
    throttle stops one account being hammered; this stops one host walking
    across many accounts (password spraying) or many addresses (mail-bombing).

    Subclasses declare a ``scope`` and NOTHING else — the rate is resolved from
    ``DEFAULT_THROTTLE_RATES`` so it is tunable per environment without a code
    change. Never hardcode ``rate``: ``SimpleRateThrottle.__init__`` only
    consults the settings table when ``rate`` is falsy, so a class attribute
    silently turns the settings entry into dead config.
    """

    #: Marker read by ``tests/architecture/test_auth_throttle_ip_ceiling.py``.
    ip_keyed = True

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


# ---------------------------------------------------------------------------
# Authentication throttles
#
# None of these declare a ``rate``. That is load-bearing, not an omission:
# ``SimpleRateThrottle.__init__`` only calls ``get_rate()`` when ``rate`` is
# falsy, so a class attribute WINS over ``DEFAULT_THROTTLE_RATES`` and turns
# the settings entry into dead config that looks authoritative and does
# nothing. Rates live in ``api/settings/base.py``; per-environment relief lives
# in ``local.py``. Adding a ``rate`` here re-breaks both.
#
# A missing scope in ``DEFAULT_THROTTLE_RATES`` now raises
# ``ImproperlyConfigured`` at first use rather than silently falling back —
# which is the point: the rate is either declared where operators look for it,
# or the endpoint refuses to serve.
# ---------------------------------------------------------------------------


class LoginThrottle(_ScopedIdentityThrottle):
    scope = "auth_login"


class PasswordResetRequestThrottle(_ScopedIdentityThrottle):
    scope = "auth_password_reset_request"


class PasswordResetConfirmThrottle(_ScopedIdentityThrottle):
    scope = "auth_password_reset_confirm"


class EmailVerifyThrottle(_ScopedIdentityThrottle):
    scope = "auth_email_verify"


class ResendVerificationEmailThrottle(_ScopedIdentityThrottle):
    """Per-email (falling back to per-IP) resend-verification throttle.

    Tight (3/hour by default) because every accepted request can enqueue a
    real email send for the named address — flooding it would both spam the
    inbox and burn the SMTP/SES sender reputation.
    """

    scope = "auth_resend_verification"


class ResendVerificationIPThrottle(_ScopedIPThrottle):
    """Strict per-client-IP ceiling on resend-verification requests.

    Sits ALONGSIDE the per-email throttle: rotating the email in the body
    must not buy an attacker unlimited sends from one host, and the always
    -202 response means there's no feedback loop to tune enumeration with.

    This was the repo's first (and until now only) per-IP auth ceiling; it
    hand-rolled ``get_cache_key`` and hardcoded its rate. Both now come from
    ``_ScopedIPThrottle`` + ``DEFAULT_THROTTLE_RATES``. The effective rate is
    unchanged (10/hour) — see ``base.py``.
    """

    scope = "auth_resend_verification_ip"


class MagicLinkRequestThrottle(_ScopedIdentityThrottle):
    """Anonymous magic-link request throttle.

    Tight rate (5/hour by default) because this endpoint sends real email —
    an attacker who could enumerate accounts by flooding it would also blow
    up the SES bounce/complaint rate. Note this keys on the CALLER-supplied
    email, so it is not a per-host limit; AuthEmailSendIPThrottle is.
    """

    scope = "auth_magic_link_request"


class MagicLinkVerifyThrottle(_ScopedIdentityThrottle):
    """Verify-side throttle.

    Defence-in-depth against brute-force guessing of the 256-bit
    token. The token itself is uncrackable in any realistic horizon,
    but a flood of verify attempts is still an early-warning signal
    worth rate-limiting.
    """

    scope = "auth_magic_link_verify"


# ---------------------------------------------------------------------------
# Per-IP ceilings for the anonymous auth surface
#
# Every throttle above keys on an identity the CALLER supplies, so none of
# them bounds what a single host can do across many identities. These do.
# Each anonymous auth view stacks exactly one identity throttle + at least one
# of these; the rates live in DEFAULT_THROTTLE_RATES so they are tunable for a
# customer with unusual egress without shipping code.
# ---------------------------------------------------------------------------


class LoginIPBurstThrottle(_ScopedIPThrottle):
    """Short-window brake on login attempts from one host.

    Catches the automated hammer within seconds. Deliberately generous per
    minute — no human-driven office produces this many login POSTs in 60s,
    but a script produces them in one — and it fully recovers in a minute,
    so even a large shared-egress customer that trips it is barely
    inconvenienced.
    """

    scope = "auth_login_ip"


class LoginIPSustainedThrottle(_ScopedIPThrottle):
    """The anti-spraying ceiling: total login attempts per host per hour.

    The burst brake alone does not stop password spraying — a sprayer happily
    paces itself under any per-minute limit. This bounds the daily total from
    one host instead, which is what makes a single-VPS spray uneconomic.

    It cannot stop a distributed attacker, and is not meant to; account
    lockout (email-keyed, 10 failures) is the second layer and covers the
    per-account case. This layer covers the one-host-many-accounts case that
    lockout structurally cannot see.
    """

    scope = "auth_login_ip_sustained"


class AuthEmailSendIPThrottle(_ScopedIPThrottle):
    """Shared ceiling on endpoints where one request sends one real email.

    Password-reset requests and magic-link requests both mint and send mail to
    a caller-named address. Per-email throttling does not bound them at all —
    rotate the address and one host can mail-bomb arbitrary inboxes and burn
    our SES sender reputation, which is shared across every customer.

    One shared bucket rather than one per endpoint: the resource being
    protected (outbound mail reputation) is shared, so the budget should be
    too, and an attacker must not double it by alternating endpoints.
    """

    scope = "auth_email_send_ip"


class AuthTokenVerifyIPThrottle(_ScopedIPThrottle):
    """Shared ceiling on the anonymous token-redemption endpoints.

    Email verification, password-reset confirm/complete and magic-link verify
    all take an opaque token and say whether it was good. The tokens are not
    realistically guessable, so this is defence-in-depth and an early-warning
    signal rather than the primary control — but without it a single host can
    grind these endpoints forever, because appending ``?email=<random>`` to
    the request is enough to mint a fresh identity bucket every time.

    Kept generous because corporate mail security (Defender for O365,
    Proofpoint) prefetches links in email, so legitimate traffic here arrives
    in bursts from scanner IPs the user never chose.
    """

    scope = "auth_token_verify_ip"


# ---------------------------------------------------------------------------
# OTP / 2FA throttles
# ---------------------------------------------------------------------------


class OTPVerifyThrottle(_ScopedPrincipalThrottle):
    """Throttle OTP verification attempts per principal."""

    scope = "otp_verify"


class StaticVerifyThrottle(_ScopedPrincipalThrottle):
    """Throttle static recovery code verification attempts per principal."""

    scope = "otp_static_verify"
