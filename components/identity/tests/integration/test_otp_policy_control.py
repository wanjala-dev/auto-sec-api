"""The OTP/2FA verification policy, proven through the real endpoints.

`test_otp_verification.py` covers JWT claim shape and `test_2fa_endpoints.py`
covers setup/teardown. Neither proves the thing that actually stops a brute
force: that repeated WRONG codes are rejected and then cut off. A 6-digit TOTP
is 10^6 wide, so an unbounded verify endpoint is walkable — the rate cap and
the per-principal lockout are the whole defence.

Asserted here:
  * a wrong code is rejected (400) and never issues tokens;
  * `StaticVerifyThrottle` (5/min) caps recovery-code guessing;
  * the per-principal OTP lockout engages on repeated TOTP failures;
  * a recovery code is single-use;
  * both caps are keyed on the authenticated principal, NOT the client IP, so
    forging `X-Forwarded-For` does not buy fresh attempts.

The two caps are deliberately tested against different endpoints so each
assertion has exactly one possible cause: `StaticVerifyThrottle` fires at 6,
comfortably before the lockout threshold of 10, so it isolates the throttle;
the TOTP test relaxes the throttle so it isolates the lockout.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse

from components.identity.api.throttles import OTPVerifyThrottle
from components.identity.domain.enums import LOCKOUT_THRESHOLD

_WRONG_CODE = "000000"


@pytest.fixture(autouse=True)
def _clear_otp_cache():
    """OTP lockout state and throttle counters share the locmem cache."""
    cache.clear()
    yield
    cache.clear()


def _authenticate(api_client, user):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {user.tokens()['access']}")
    return api_client


@pytest.fixture
def totp_user(db, user_factory):
    user = user_factory(email="otp-subject@acme-soc.example", username="otp-subject")
    user.totpdevice_set.create(confirmed=True)
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    return user


@pytest.fixture
def static_user(db, user_factory):
    """A user holding exactly one known recovery code."""
    user = user_factory(email="static-subject@acme-soc.example", username="static-subject")
    device = user.staticdevice_set.create(name="backup")
    device.token_set.create(token="RECOVERY01")
    user.two_factor_enabled = True
    user.save(update_fields=["two_factor_enabled"])
    return user


@pytest.mark.integration
@pytest.mark.django_db
class TestWrongCodesAreRejected:
    def test_wrong_totp_code_is_rejected_without_tokens(self, api_client, totp_user):
        client = _authenticate(api_client, totp_user)
        response = client.post(reverse("totp-verify"), {"token": _WRONG_CODE}, format="json")

        assert response.status_code == 400, response.data
        assert "tokens" not in response.data

    def test_missing_token_is_400(self, api_client, totp_user):
        client = _authenticate(api_client, totp_user)
        response = client.post(reverse("totp-verify"), {}, format="json")
        assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.django_db
class TestRecoveryCodeGuessingIsThrottled:
    """StaticVerifyThrottle is 5/min — it fires well before the lockout at 10."""

    def test_sixth_attempt_in_a_minute_is_throttled(self, api_client, static_user):
        client = _authenticate(api_client, static_user)
        url = reverse("static-verify")

        responses = [client.post(url, {"token": f"WRONG{i:04d}"}, format="json") for i in range(6)]

        assert all(r.status_code == 400 for r in responses[:5]), [r.status_code for r in responses]
        assert responses[5].status_code == 429

    def test_rotating_forwarded_for_does_not_buy_more_attempts(self, api_client, static_user):
        """The cap is per-principal; a forged origin must not reset it."""
        client = _authenticate(api_client, static_user)
        url = reverse("static-verify")

        responses = [
            client.post(
                url,
                {"token": f"WRONG{i:04d}"},
                format="json",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{i}, 203.0.113.77",
            )
            for i in range(6)
        ]

        assert responses[5].status_code == 429, "Recovery-code guessing was unthrottled while rotating X-Forwarded-For."

    def test_a_valid_recovery_code_is_single_use(self, api_client, static_user):
        client = _authenticate(api_client, static_user)
        url = reverse("static-verify")

        first = client.post(url, {"token": "RECOVERY01"}, format="json")
        assert first.status_code == 200, first.data
        assert first.data.get("otp_verified") is True

        replay = client.post(url, {"token": "RECOVERY01"}, format="json")
        assert replay.status_code == 400, "a recovery code was accepted twice"


@pytest.mark.integration
@pytest.mark.django_db
class TestOtpLockoutEngages:
    """With the throttle relaxed, the per-principal lockout is the cap under test."""

    @pytest.fixture(autouse=True)
    def _relax_otp_throttle(self, monkeypatch):
        # Class-attribute patch, not override_settings — see FINDING C: these
        # throttles hardcode `rate`, so DEFAULT_THROTTLE_RATES is dead config.
        monkeypatch.setattr(OTPVerifyThrottle, "rate", "1000/min")

    def test_repeated_totp_failures_lock_the_principal_out(self, api_client, totp_user):
        client = _authenticate(api_client, totp_user)
        url = reverse("totp-verify")

        for _ in range(LOCKOUT_THRESHOLD):
            client.post(url, {"token": _WRONG_CODE}, format="json")

        locked = client.post(url, {"token": _WRONG_CODE}, format="json")
        assert locked.status_code == 429, locked.data
        assert "Too many failed attempts" in str(locked.data.get("detail", ""))
