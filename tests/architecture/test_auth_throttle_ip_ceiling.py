"""Anonymous auth endpoints must always keep a per-IP ceiling.

THE DRIFT THIS EXISTS TO STOP
-----------------------------
DRF's ``DEFAULT_THROTTLE_CLASSES`` (``AnonRateThrottle`` + ``UserRateThrottle``)
is the only thing giving most of this API a per-IP limit. Declaring
``throttle_classes`` on a view does not ADD to that list — it **replaces** it.
So the perfectly reasonable-looking::

    throttle_classes = [LoginThrottle]

silently deletes the global anon ceiling from that endpoint. If the throttle
you put there keys on something the caller supplies — an email in the body, or
in the query string — the endpoint ends up with *no* per-host limit at all.
That is how login came to have no defence against password spraying: every
rotated email landed in its own bucket, from one host, forever.

The same trap is waiting for the next auth endpoint anyone adds, and it is
invisible in review because the view *looks* throttled. Hence this fitness
function rather than a comment.

THE RULE
--------
Every anonymous-reachable view on the identity URLconf must resolve at least
one throttle whose bucket key is the client IP **and nothing else** —
``_ScopedIPThrottle`` (marked ``ip_keyed``) or DRF's ``AnonRateThrottle``.

Views that require authentication are exempt: DRF checks permissions before
throttles, so an anonymous caller never reaches their throttle, and the right
bucket for them is the principal, not the host.

Note what this rule does NOT require: it does not force a view to declare
anything. A view that declares no ``throttle_classes`` inherits the global
``AnonRateThrottle`` and passes automatically. It only fires when a view opts
out of the global default and fails to put an IP ceiling back.
"""

from __future__ import annotations

import pytest
from django.urls import URLPattern, URLResolver
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle

from components.identity.api import urls as identity_urls

pytestmark = pytest.mark.arch


def _iter_view_classes(patterns, prefix=""):
    """Yield ``(route, view_class)`` for every DRF view on a URLconf."""
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _iter_view_classes(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            view_class = getattr(entry.callback, "cls", None)
            if view_class is not None:
                yield prefix + str(entry.pattern), view_class


def _is_anonymous_reachable(view_class) -> bool:
    """True when an unauthenticated caller can reach this view's handler.

    Conservative by construction: anything that does not explicitly demand an
    authenticated (or admin) principal is treated as anonymous-reachable, so a
    new custom permission class defaults into the rule rather than out of it.
    """
    permission_classes = getattr(view_class, "permission_classes", ()) or ()
    return not any(permission is IsAuthenticated or permission is IsAdminUser for permission in permission_classes)


def _resolves_ip_keyed_throttle(view_class) -> bool:
    """True when the view's own throttle stack contains a pure per-IP throttle.

    Calls ``get_throttles()`` rather than reading ``throttle_classes``, because
    several identity views set ``throttle_classes = []`` and build the real
    stack in a ``get_throttles()`` override — reading the attribute would score
    those as unthrottled and, worse, would let a future override slip an
    IP-less stack past this test.
    """
    for throttle in view_class().get_throttles():
        if getattr(throttle, "ip_keyed", False) or isinstance(throttle, AnonRateThrottle):
            return True
    return False


IDENTITY_VIEWS = sorted(
    set(_iter_view_classes(identity_urls.urlpatterns)), key=lambda pair: (pair[0], pair[1].__name__)
)


def test_identity_urlconf_is_actually_scanned():
    """Guard the guard: a broken import would make every assertion below vacuous."""
    assert len(IDENTITY_VIEWS) >= 20, (
        f"Only {len(IDENTITY_VIEWS)} identity views were discovered — the URLconf walk is broken, "
        "so the per-IP ceiling rule below is silently passing on an empty set."
    )


@pytest.mark.parametrize(
    ("route", "view_class"),
    [
        pytest.param(route, view_class, id=f"{view_class.__name__}@{route or '/'}")
        for route, view_class in IDENTITY_VIEWS
    ],
)
def test_anonymous_auth_views_keep_an_ip_keyed_throttle(route, view_class):
    if not _is_anonymous_reachable(view_class):
        pytest.skip(f"{view_class.__name__} requires an authenticated principal — per-principal throttling is correct")

    assert _resolves_ip_keyed_throttle(view_class), (
        f"{view_class.__name__} (/identity/{route}) is reachable anonymously but resolves no IP-keyed "
        "throttle.\n\n"
        "Declaring `throttle_classes` REPLACES DEFAULT_THROTTLE_CLASSES, so this view no longer has the "
        "global AnonRateThrottle — and identity's own throttles key on an email read from the request "
        "body OR query string, which the caller controls. Net effect: one host can rotate that value and "
        "make unlimited requests.\n\n"
        "Fix: stack a `_ScopedIPThrottle` subclass (components/identity/api/throttles.py) alongside the "
        "identity throttle. Give it a `scope`, add the rate to DEFAULT_THROTTLE_RATES, and do NOT set "
        "`rate` on the class."
    )


def test_login_carries_both_a_burst_and_a_sustained_ip_ceiling():
    """Login is the spraying target — one IP tier is not enough there.

    A burst limit alone is trivially defeated by pacing the attack under it; a
    sustained limit alone still lets a fast burst through before it engages.
    Spelled out as its own assertion so that dropping either tier during a
    rate-tuning pass fails loudly instead of quietly halving the control.
    """
    from components.identity.api.controller import LoginAPIView

    durations = {
        throttle.duration for throttle in LoginAPIView().get_throttles() if getattr(throttle, "ip_keyed", False)
    }

    assert len(durations) >= 2, (
        "LoginAPIView must carry TWO per-IP throttles over different windows — a short-window burst "
        f"brake and a long-window anti-spraying ceiling. Found windows (seconds): {sorted(durations)}."
    )
