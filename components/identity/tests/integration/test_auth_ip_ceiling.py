"""The anonymous auth surface must bound what ONE HOST can do.

WHY THIS FILE EXISTS
--------------------
Identity's throttles key on an identity the CALLER supplies —
``_ScopedIdentityThrottle`` reads ``email`` from the request body *or* the
query string. That bounds an attack on one account and nothing else. And
because declaring ``throttle_classes`` on a DRF view REPLACES
``DEFAULT_THROTTLE_CLASSES``, the global ``AnonRateThrottle`` that would have
supplied a per-host ceiling was silently gone from every one of these
endpoints.

Net effect before this change: **password spraying was unthrottled**. One host,
one password, a fresh email per request — every attempt landed in its own
bucket. Account lockout could not see it either: lockout is keyed by email, so
one attempt per account never trips it. That is precisely the shape of a spray.

The tests below fix the two halves of the argument in place: the attack is now
stopped, and the honest shared-egress customer (an office NAT, a VPN, a carrier
CGNAT — very normal for our buyers) is not collateral damage.

ON RATES IN TESTS
-----------------
The IP throttles are patched down to small numbers via ``THROTTLE_RATES`` so a
test can reach them in a few requests. That the patch WORKS AT ALL is itself
part of the contract: the new throttles declare a ``scope`` and no ``rate``, so
``SimpleRateThrottle.get_rate()`` really does consult the settings table. A
throttle that hardcoded ``rate`` would ignore this patch — and would ignore
``DEFAULT_THROTTLE_RATES`` in production too.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse

from components.identity.api.throttles import _ScopedIPThrottle

pytestmark = pytest.mark.django_db

# One proxy (the NGINX Gateway Fabric data plane) appends its view of the TCP
# peer, so the trusted hop is the RIGHTMOST entry. See #310 / client_ip.py.
_OFFICE_EGRESS = "203.0.113.40"
_OTHER_EGRESS = "203.0.113.41"


def _from_host(peer: str, *, spoofed: str | None = None) -> str:
    return f"{spoofed}, {peer}" if spoofed else peer


@pytest.fixture(autouse=True)
def _isolate_throttle_state(settings):
    """DRF counts throttle hits in the process-wide cache — isolate each test."""
    settings.SECURITY_EVENTS_ASYNC = False
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ip_rates(monkeypatch):
    """Patch the per-IP rate table only, leaving identity throttles at real rates.

    Patched on ``_ScopedIPThrottle`` rather than ``SimpleRateThrottle`` so the
    email-keyed throttles keep resolving their production rates — otherwise a
    test could pass because the wrong throttle fired.
    """

    def _apply(**scopes: str) -> None:
        monkeypatch.setattr(
            _ScopedIPThrottle,
            "THROTTLE_RATES",
            {**_ScopedIPThrottle.THROTTLE_RATES, **scopes},
        )

    return _apply


def _verified_user(user_factory, **kwargs):
    user = user_factory(password="pass1234", **kwargs)
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


def _attempt_login(api_client, *, email: str, password: str = "hunter2", peer: str = _OFFICE_EGRESS, spoofed=None):
    return api_client.post(
        reverse("login"),
        {"email": email, "password": password},
        format="json",
        HTTP_X_FORWARDED_FOR=_from_host(peer, spoofed=spoofed),
    )


class TestPasswordSprayingIsBounded:
    """THE FINDING: many accounts, one password, one host."""

    def test_spraying_across_many_emails_from_one_host_is_throttled(self, api_client, ip_rates):
        """Each request uses a DIFFERENT email, so no per-email limit and no
        account lockout can ever engage. Only a per-IP ceiling can stop this.
        """
        ip_rates(auth_login_ip="5/min")

        statuses = [_attempt_login(api_client, email=f"spray-{i}@target.example").status_code for i in range(7)]

        assert 429 in statuses, (
            "Password spraying is unthrottled: rotating the email produced "
            f"{len([s for s in statuses if s != 429])} accepted attempts from a single host "
            f"against a 5/min per-IP cap. Statuses: {statuses}"
        )
        assert statuses[5] == 429, f"the cap engaged late or early: {statuses}"

    def test_the_sustained_ceiling_catches_a_sprayer_pacing_under_the_burst_brake(self, api_client, ip_rates):
        """A real sprayer paces itself. The burst brake alone would never fire.

        Burst is left wide open here to prove the SUSTAINED tier is doing the
        work independently — this is why login carries two tiers, not one.
        """
        ip_rates(auth_login_ip="1000/min", auth_login_ip_sustained="4/hour")

        statuses = [_attempt_login(api_client, email=f"paced-{i}@target.example").status_code for i in range(6)]

        assert statuses[4] == 429, (
            "A sprayer staying under the per-minute brake was never stopped — the sustained "
            f"per-hour ceiling did not engage. Statuses: {statuses}"
        )

    def test_a_spoofed_forwarded_for_does_not_mint_a_fresh_bucket(self, api_client, ip_rates):
        """The ceiling must key on the hop OUR gateway wrote, not the caller's.

        Belt-and-braces over #310: that fix set NUM_PROXIES globally; this
        asserts the login ceiling specifically inherits the benefit, since a
        forgeable key would make the whole control decorative.
        """
        ip_rates(auth_login_ip="5/min")

        statuses = [
            _attempt_login(
                api_client,
                email=f"spoof-{i}@target.example",
                spoofed=f"198.51.100.{i}",
            ).status_code
            for i in range(7)
        ]

        assert 429 in statuses, f"rotating X-Forwarded-For evaded the login IP ceiling: {statuses}"

    def test_an_email_in_the_query_string_does_not_evade_the_ceiling(self, api_client, ip_rates):
        """`_ScopedIdentityThrottle` reads `email` from the QUERY STRING too.

        So an attacker can attach `?email=<random>` to an endpoint whose real
        payload has no email and knock it off its `ip:` fallback. The explicit
        IP throttle is the thing that cannot be steered this way.
        """
        ip_rates(auth_login_ip="5/min")

        statuses = [
            api_client.post(
                f"{reverse('login')}?email=evade-{i}@target.example",
                {"email": "victim@target.example", "password": "hunter2"},
                format="json",
                HTTP_X_FORWARDED_FOR=_from_host(_OFFICE_EGRESS),
            ).status_code
            for i in range(7)
        ]

        assert 429 in statuses, f"a rotating query-string email evaded the per-IP ceiling: {statuses}"


class TestHonestUsersAreNotCollateralDamage:
    """The ceiling is worthless if it locks out a customer's office."""

    def test_a_team_behind_one_egress_ip_logs_in_normally_at_production_rates(self, api_client, user_factory):
        """No rate patching: this runs against the REAL configured rates.

        Twelve teammates behind one NAT — a customer office, a VPN, a carrier
        CGNAT — all logging in within the same window. If the shipped rate
        cannot absorb this, it is too tight to ship.
        """
        users = [_verified_user(user_factory, email=f"teammate{i}@customer.example") for i in range(12)]

        statuses = [_attempt_login(api_client, email=user.email, password="pass1234").status_code for user in users]

        assert statuses.count(200) == len(users), (
            f"Legitimate shared-egress logins were rejected at production rates: {statuses}. "
            "The per-IP ceiling is too tight for a normal customer office."
        )

    def test_one_user_retrying_a_typo_is_not_throttled(self, api_client, user_factory):
        """Fat-fingering a password a few times must not lock anyone out of the host."""
        user = _verified_user(user_factory, email="typo@customer.example")

        for _ in range(3):
            assert _attempt_login(api_client, email=user.email, password="wrong").status_code == 401

        assert _attempt_login(api_client, email=user.email, password="pass1234").status_code == 200

    def test_a_throttled_host_does_not_throttle_a_different_host(self, api_client, ip_rates):
        """Buckets must stay per-IP, not collapse into one global counter."""
        ip_rates(auth_login_ip="3/min")

        for i in range(4):
            _attempt_login(api_client, email=f"noisy-{i}@target.example", peer=_OFFICE_EGRESS)
        assert _attempt_login(api_client, email="x@target.example", peer=_OFFICE_EGRESS).status_code == 429

        other = _attempt_login(api_client, email="elsewhere@customer.example", peer=_OTHER_EGRESS)
        assert other.status_code != 429, "throttle buckets collapsed — one customer's traffic throttles another's"


class TestTheEmailKeyedLayerStillWorks:
    """Adding the IP ceiling must not weaken the per-account control."""

    def test_hammering_one_account_still_trips_the_per_email_throttle(self, api_client, ip_rates):
        """Same email every time, and the IP ceiling deliberately left wide open
        so that whatever fires must be the email-keyed throttle (10/min).
        """
        ip_rates(auth_login_ip="1000/min", auth_login_ip_sustained="1000/hour")

        statuses = [
            _attempt_login(api_client, email="victim@target.example", spoofed=f"198.51.100.{i}").status_code
            for i in range(12)
        ]

        assert 429 in statuses, (
            f"the per-email login throttle no longer engages when one account is hammered: {statuses}"
        )

    def test_account_lockout_still_engages_and_is_not_reset_by_moving_ip(self, api_client, user_factory, ip_rates):
        """Lockout is the second layer this ceiling is calibrated against.

        The per-IP ceiling is deliberately generous *because* lockout covers
        the single-account case — so if lockout regressed, the chosen rate
        would no longer be defensible. Asserted here rather than assumed.
        """
        ip_rates(auth_login_ip="1000/min", auth_login_ip_sustained="1000/hour")
        user = _verified_user(user_factory, email="lockme@customer.example")

        for i in range(10):
            _attempt_login(api_client, email=user.email, password="wrong", spoofed=f"198.51.100.{i}")

        # Correct password, and a fresh source IP — lockout must still hold.
        blocked = _attempt_login(api_client, email=user.email, password="pass1234", peer=_OTHER_EGRESS)
        assert blocked.status_code != 200, (
            "account lockout did not hold: the correct password was accepted after 10 failures, "
            "or lockout was reset by changing the client IP"
        )


class TestSiblingAuthEndpointsAlsoHaveACeiling:
    """The same trap applied to every endpoint that declared throttle_classes."""

    def test_rotating_the_address_cannot_mail_bomb_via_password_reset(self, api_client, ip_rates):
        """Each accepted request sends real mail to a caller-named inbox. The
        per-email limit bounds nothing when the attacker picks the email.
        """
        ip_rates(auth_email_send_ip="4/hour")

        statuses = [
            api_client.post(
                reverse("request-reset-email"),
                {"email": f"bomb-{i}@victim.example"},
                format="json",
                HTTP_X_FORWARDED_FOR=_from_host(_OFFICE_EGRESS),
            ).status_code
            for i in range(6)
        ]

        assert 429 in statuses, (
            f"one host could request unlimited password-reset emails to arbitrary addresses: {statuses}"
        )

    def test_the_email_send_budget_is_shared_across_endpoints(self, api_client, ip_rates):
        """Password-reset and magic-link requests share one bucket on purpose —
        they consume the same shared resource (our SES sender reputation), so
        alternating between them must not double an attacker's allowance.
        """
        ip_rates(auth_email_send_ip="4/hour")

        for i in range(4):
            api_client.post(
                reverse("request-reset-email"),
                {"email": f"drain-{i}@victim.example"},
                format="json",
                HTTP_X_FORWARDED_FOR=_from_host(_OFFICE_EGRESS),
            )

        spillover = api_client.post(
            reverse("magic-link-request"),
            {"email": "spillover@victim.example"},
            format="json",
            HTTP_X_FORWARDED_FOR=_from_host(_OFFICE_EGRESS),
        )
        assert spillover.status_code == 429, (
            "the outbound-mail budget is not shared: an attacker doubles their allowance "
            "by alternating between password-reset and magic-link requests"
        )
