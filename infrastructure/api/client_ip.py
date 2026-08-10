"""The ONE place that decides which IP in a request belongs to the client.

`X-Forwarded-For` is an append-only audit trail written by proxies, and only
the hops appended by proxies WE control are trustworthy. Everything to the left
of those is whatever the caller typed. Any code that reads the header itself and
takes ``split(",")[0]`` is reading attacker-controlled input — that is fine for
"which CDN edge served this" telemetry and catastrophic for anything that gates,
counts, or is later used as evidence.

DRF already derives this correctly for throttling via ``NUM_PROXIES``
(see ``rest_framework.throttling.BaseThrottle.get_ident``). This module applies
the SAME rule to the non-throttle consumers — audit events, session records,
login activity, the honeypot — so there is exactly one derivation in the
codebase and one setting to get right.

See ``api/settings/base.py`` for how ``NUM_PROXIES`` is derived per environment.
"""

from __future__ import annotations

from rest_framework.settings import api_settings


def trusted_client_ip(request) -> str | None:
    """Return the client IP from the rightmost hop this deployment trusts.

    Mirrors DRF's ``BaseThrottle.get_ident()`` with one deliberate difference:
    an unset ``NUM_PROXIES`` is treated as ``0`` (trust only ``REMOTE_ADDR``)
    rather than DRF's "use the whole header". Misconfiguration should degrade
    to a blunt-but-honest value, never to an attacker-chosen one.
    """
    remote_addr = request.META.get("REMOTE_ADDR") or None
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    num_proxies = api_settings.NUM_PROXIES
    if num_proxies is None:
        num_proxies = 0

    if num_proxies <= 0 or not forwarded_for:
        return remote_addr

    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    if not hops:
        return remote_addr

    # Count trusted hops from the RIGHT. If the header is shorter than the
    # configured proxy count (a proxy that didn't append, or a direct hit on an
    # internal address), clamping to the leftmost entry is the conservative
    # read — it can only ever be a hop that reached us, never one we skipped.
    return hops[-min(num_proxies, len(hops))]
