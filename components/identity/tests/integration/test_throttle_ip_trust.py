"""The IP-keyed throttles must key on an IP the CLIENT cannot choose.

Every anonymous rate limit in this API is keyed on "the client's IP", derived
by DRF's ``BaseThrottle.get_ident()``. That derivation is only sound when
``NUM_PROXIES`` tells DRF how many trusted reverse proxies sit in front of
Django. With it unset, ``get_ident()`` falls through to::

    return ''.join(xff.split()) if xff else remote_addr

— the WHOLE ``X-Forwarded-For`` header becomes the throttle bucket key. Since
the left-hand entries of that header are supplied by the caller, an attacker
gets a brand-new bucket per request just by rotating a header value, and every
anon rate limit in the product evaporates.

These tests model the real deployment honestly. In both local and prod, exactly
ONE proxy (the NGINX Gateway Fabric data plane) sits between the client and
gunicorn, and it APPENDS its view of the peer to ``X-Forwarded-For``. So the
header Django sees is::

    X-Forwarded-For: <whatever the attacker sent>, <the real peer>
                     \\_______ attacker-controlled ______/  \\__ trusted __/

``_through_proxy()`` below builds exactly that. The trusted client IP is the
RIGHTMOST entry — the only one an attacker cannot forge.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.settings import api_settings

RESEND_URL = "/identity/resend-verification/"

# The resend-verification endpoint carries a pure per-IP throttle
# (ResendVerificationIPThrottle, 10/hour) alongside its per-email one, which
# makes it the cleanest probe for IP-keyed throttle integrity: rotating the
# email in the body deliberately does NOT buy extra requests, so anything that
# does get through is an IP-derivation defect.
_RESEND_IP_CAP = 10

_ATTACKER_PEER = "203.0.113.77"


def _through_proxy(*, peer: str = _ATTACKER_PEER, spoofed: str | None = None) -> str:
    """Build the ``X-Forwarded-For`` value Django sees behind ONE proxy.

    ``spoofed`` is whatever the attacker put in the header; the gateway then
    appends ``peer``, its own (unforgeable) view of the TCP peer.
    """
    return f"{spoofed}, {peer}" if spoofed else peer


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """DRF throttles count in the process-wide locmem cache — isolate tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.integration
@pytest.mark.django_db
class TestNumProxiesIsConfigured:
    """The setting the whole IP-trust story rests on."""

    def test_num_proxies_is_set(self):
        """Unset means 'trust the entire client-supplied header' — never ship that."""
        assert api_settings.NUM_PROXIES is not None, (
            "NUM_PROXIES is unset, so DRF's get_ident() keys throttles on the raw "
            "X-Forwarded-For header, which the client controls. Set it to the number "
            "of trusted proxies in front of Django for this environment."
        )
        assert api_settings.NUM_PROXIES >= 0


@pytest.mark.integration
@pytest.mark.django_db
class TestAnonThrottleResistsSpoofedForwardedFor:
    """The reproduction: a rotating X-Forwarded-For must not mint fresh buckets."""

    def _resend(self, api_client, *, xff: str, email: str):
        return api_client.post(
            RESEND_URL,
            {"email": email},
            format="json",
            HTTP_X_FORWARDED_FOR=xff,
        )

    def test_baseline_throttle_engages_for_an_honest_client(self, api_client):
        """Sanity: without any spoofing the per-IP cap is real."""
        xff = _through_proxy()
        responses = [
            self._resend(api_client, xff=xff, email=f"honest-{i}@acme-soc.example") for i in range(_RESEND_IP_CAP + 1)
        ]
        assert all(r.status_code == 202 for r in responses[:_RESEND_IP_CAP])
        assert responses[_RESEND_IP_CAP].status_code == 429

    def test_rotating_spoofed_forwarded_for_does_not_evade_the_cap(self, api_client):
        """THE DEFECT.

        Same TCP peer, a different forged left-hand XFF entry each time. If the
        client IP is derived from anything the caller can influence, every
        request lands in its own bucket and the limit never fires.
        """
        responses = [
            self._resend(
                api_client,
                xff=_through_proxy(spoofed=f"198.51.100.{i}"),
                email=f"spoof-{i}@acme-soc.example",
            )
            for i in range(_RESEND_IP_CAP + 1)
        ]
        statuses = [r.status_code for r in responses]
        assert 429 in statuses, (
            "Throttle bypassed: rotating the client-supplied X-Forwarded-For prefix "
            f"produced {statuses.count(202)} accepted requests against a "
            f"{_RESEND_IP_CAP}/hour per-IP cap. The throttle key is attacker-controlled."
        )
        assert statuses[_RESEND_IP_CAP] == 429

    def test_a_long_forged_hop_chain_does_not_evade_the_cap(self, api_client):
        """Padding the header with many forged hops must not shift the trusted hop."""
        responses = [
            self._resend(
                api_client,
                xff=_through_proxy(spoofed=", ".join(f"10.0.0.{h}" for h in range(i + 1))),
                email=f"chain-{i}@acme-soc.example",
            )
            for i in range(_RESEND_IP_CAP + 1)
        ]
        assert responses[_RESEND_IP_CAP].status_code == 429

    def test_distinct_real_peers_still_get_their_own_buckets(self, api_client):
        """The fix must not collapse every client into one global bucket."""
        for i in range(_RESEND_IP_CAP):
            resp = self._resend(
                api_client,
                xff=_through_proxy(peer="203.0.113.10"),
                email=f"peer-a-{i}@acme-soc.example",
            )
            assert resp.status_code == 202

        # A genuinely different client must be unaffected by A's exhausted quota.
        resp = self._resend(
            api_client,
            xff=_through_proxy(peer="203.0.113.11"),
            email="peer-b@acme-soc.example",
        )
        assert resp.status_code == 202, "Throttle buckets collapsed — distinct clients share one key."
