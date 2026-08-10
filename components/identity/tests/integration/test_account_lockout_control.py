"""The account-lockout control, proven end-to-end through the real endpoint.

`components/identity/tests/unit/test_auth_lockout_policy.py` already covers the
pure policy function exhaustively. Nothing proved the LOGIN ENDPOINT actually
applies it — which is the thing we claim in the security posture. These tests
drive `POST /identity/login/` and assert the observable behaviour:

  * warn fires at LOCKOUT_WARN_AT (7) with the remaining-attempts count;
  * lockout engages at LOCKOUT_THRESHOLD (10);
  * once locked, the CORRECT password is still refused — a lockout that a
    valid credential walks through is not a lockout;
  * a successful login clears the counter;
  * the counter is keyed on the submitted EMAIL, not on the client IP, so it
    cannot be reset by forging `X-Forwarded-For`.

That last one is the tie-in to the NUM_PROXIES work: lockout was audited as a
possible IP-spoofable control and it is not one. This test pins that down so a
future refactor toward IP-keying is a deliberate, visible decision.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.throttling import SimpleRateThrottle

from components.identity.domain.enums import (
    LOCKOUT_THRESHOLD,
    LOCKOUT_WARN_AT,
)
from infrastructure.persistence.users.models import CustomUser

LOGIN_URL = "/identity/login/"

_EMAIL = "lockout-subject@acme-soc.example"
_PASSWORD = "AutoSecLockout2026!"
_WRONG = "definitely-not-the-password"


@pytest.fixture(autouse=True)
def _clear_lockout_cache():
    """Lockout state and throttle counters share the locmem cache."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _relax_login_throttle(monkeypatch):
    """Take the rate limiter out of the way so we measure LOCKOUT, not throttling.

    LoginThrottle is 10/min per email and the lockout threshold is also 10, so
    the two controls collide exactly at the point of interest: the 11th request
    would be rejected by the throttle before the view could tell us what the
    lockout did.

    This now patches the rate TABLE, which is the honest way round: it
    exercises the real ``scope`` → ``DEFAULT_THROTTLE_RATES`` resolution in
    ``SimpleRateThrottle.get_rate()`` instead of bypassing it.

    It previously had to patch the class attribute instead, because every
    identity throttle hardcoded ``rate`` and ``SimpleRateThrottle.__init__``
    only consults the settings table when ``rate`` is falsy — so the settings
    entries were dead config (FINDING C from #310, now fixed). The login
    endpoint also carries per-IP ceilings, so those scopes are relaxed too;
    otherwise this file would measure the IP throttle rather than lockout.

    ``override_settings`` still would NOT work here: ``THROTTLE_RATES`` is
    bound to the settings dict at class-definition time, so re-reading
    ``api_settings`` does not reach it.
    """
    monkeypatch.setattr(
        SimpleRateThrottle,
        "THROTTLE_RATES",
        {
            **SimpleRateThrottle.THROTTLE_RATES,
            "auth_login": "1000/min",
            "auth_login_ip": "1000/min",
            "auth_login_ip_sustained": "1000/min",
        },
    )


@pytest.fixture
def subject(db):
    user = CustomUser.objects.create_user(
        username="lockout-subject",
        email=_EMAIL,
        password=_PASSWORD,
    )
    CustomUser.objects.filter(pk=user.pk).update(is_verified=True)
    user.refresh_from_db()
    return user


def _login(api_client, *, password, xff=None):
    extra = {"HTTP_X_FORWARDED_FOR": xff} if xff else {}
    return api_client.post(
        LOGIN_URL,
        {"email": _EMAIL, "password": password},
        format="json",
        **extra,
    )


def _detail(response) -> str:
    return str(response.data.get("detail", ""))


@pytest.mark.integration
@pytest.mark.django_db
class TestAccountLockoutIsEnforced:
    def test_bad_credentials_below_warn_threshold_stay_generic(self, api_client, subject):
        """Early failures must not leak how close the account is to locking."""
        for _ in range(LOCKOUT_WARN_AT - 1):
            response = _login(api_client, password=_WRONG)
            assert response.status_code == 401
            assert "attempts remaining" not in _detail(response)

    def test_warn_fires_at_the_warn_threshold(self, api_client, subject):
        for _ in range(LOCKOUT_WARN_AT - 1):
            _login(api_client, password=_WRONG)

        response = _login(api_client, password=_WRONG)
        assert response.status_code == 401
        detail = _detail(response)
        assert "attempts remaining" in detail, detail
        # 7 failures against a threshold of 10 leaves 3.
        assert str(LOCKOUT_THRESHOLD - LOCKOUT_WARN_AT) in detail

    def test_lockout_engages_at_the_threshold(self, api_client, subject):
        responses = [_login(api_client, password=_WRONG) for _ in range(LOCKOUT_THRESHOLD)]

        assert all(r.status_code == 401 for r in responses)
        final = _detail(responses[-1])
        assert "Too many failed login attempts" in final, final

    def test_correct_password_is_refused_while_locked(self, api_client, subject):
        """A lockout a valid credential walks straight through is not a lockout."""
        for _ in range(LOCKOUT_THRESHOLD):
            _login(api_client, password=_WRONG)

        response = _login(api_client, password=_PASSWORD)
        assert response.status_code == 401
        assert "Too many failed login attempts" in _detail(response)

    def test_successful_login_clears_the_failure_counter(self, api_client, subject):
        for _ in range(LOCKOUT_WARN_AT - 1):
            _login(api_client, password=_WRONG)

        ok = _login(api_client, password=_PASSWORD)
        assert ok.status_code == 200, ok.data

        # Counter reset: the next bad attempt is attempt #1, not #7, so it must
        # not carry the warning.
        response = _login(api_client, password=_WRONG)
        assert response.status_code == 401
        assert "attempts remaining" not in _detail(response)


@pytest.mark.integration
@pytest.mark.django_db
class TestLockoutIsNotIpKeyed:
    """Lockout is keyed on the submitted email — forging XFF must not reset it."""

    def test_rotating_forwarded_for_does_not_reset_the_counter(self, api_client, subject):
        for i in range(LOCKOUT_THRESHOLD):
            response = _login(
                api_client,
                password=_WRONG,
                # A different forged origin every single attempt.
                xff=f"198.51.100.{i}, 203.0.113.77",
            )
            assert response.status_code == 401

        # Still locked, from yet another "new" origin.
        response = _login(api_client, password=_PASSWORD, xff="198.51.100.250, 203.0.113.77")
        assert response.status_code == 401
        assert "Too many failed login attempts" in _detail(response), (
            "Lockout was evaded by rotating X-Forwarded-For — it is keyed on client-controlled input."
        )
