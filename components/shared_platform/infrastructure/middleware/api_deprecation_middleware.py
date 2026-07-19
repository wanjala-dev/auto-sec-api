"""API version deprecation middleware (RFC 9745 + RFC 8594).

Stamps standards-compliant deprecation headers on every response served by an
API version an operator has marked deprecated in
``settings.API_DEPRECATED_VERSIONS``. As of Phase 3 of the versioning roadmap,
the deprecated version is **v0**, and the middleware covers BOTH ways a client
reaches the v0 contract:

* the explicit ``/api/v0/…`` mount (carries a ``version`` URL kwarg), and
* the **unversioned root alias** (``/sponsorship/…``, ``/budget/…``, etc.) —
  which carries no ``version`` kwarg but resolves to ``DEFAULT_VERSION`` (v0).

It still NEVER touches ``/api/v1/`` (the committed successor — its ``version``
kwarg is ``'v1'``, which isn't in the config, so it's skipped), nor any
non-API-contract infra route (admin, Swagger, schema, health, MCP, i18n,
static/media). Those infra routes share the root with the unversioned alias but
are explicitly excluded by prefix (see ``_UNVERSIONED_NON_API_PREFIXES``).

It also NEVER touches **external-system webhook / ingest surfaces** (Stripe,
Plaid, SES→SNS): those URLs are registered with a third party, so they are
version-stable by contract — deprecating one would silently stop processing live
payments at the v0 sunset. They are exempt on every mount (alias AND
``/api/vN/``) via a path-fragment match (see ``_VERSION_STABLE_PATH_MARKERS``).
Webhooks are intentionally not versioned.

While a version is **within its window** (now < sunset) this is header-only — it
never changes a payload, status, or routing, so it cannot break a tolerant
client. Once a version is **past its ``sunset`` date** (Phase 4), the same
surface is short-circuited with **410 Gone** (the migration guide in the body +
the RFC headers) instead of being served — the lossless final step of the §8
lifecycle. This is config + date driven: with ``sunset`` in the future the 410
path is dormant, so no code change is needed when the date eventually passes.

Config shape (in settings)::

    API_DEPRECATED_VERSIONS = {
        "v0": {
            "deprecation": "2026-06-19T00:00:00Z",  # when it took effect (RFC 9745)
            "sunset": "2027-06-19T00:00:00Z",       # when it stops responding (RFC 8594)
            "successor": "/api/v1/",                 # rel="successor-version"
            "link": "https://…/migrating-v0-v1.md",  # rel="deprecation"
        },
    }

See the ``api-versioning`` skill §8 and ADR 0006.
"""

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import JsonResponse
from django.utils.http import http_date

from infrastructure.api.versioning import REQUEST_VERSION_ATTR

logger = logging.getLogger(__name__)

#: Path prefixes that share the root with the unversioned API alias but are NOT
#: part of the public API contract, so they must never be stamped as deprecated.
#: These mirror ``infra_patterns`` in ``api/urls.py`` (admin, schema/Swagger/Redoc,
#: health, MCP, i18n) plus Django's static/media roots. The ``/api/`` prefix here
#: catches ``/api/schema…`` and ``/api/health…``; the explicitly-versioned
#: ``/api/v0/`` and ``/api/v1/`` mounts never reach the unversioned branch (they
#: carry a ``version`` kwarg and are handled before this check).
_UNVERSIONED_NON_API_PREFIXES = (
    "/api/",       # /api/schema, /api/schema/redoc, /api/health, /api/health/celery
    "/octopus/",   # Django admin
    "/admin/",     # admin honeypot
    "/mcp/",       # MCP tool surface
    "/i18n/",      # set_language
    "/static/",    # collected static assets
    "/media/",     # uploaded media
)

#: Path fragments that mark a route as a **version-stable webhook / ingest
#: surface** — endpoints whose URL is registered with an EXTERNAL system (Stripe,
#: Plaid, SES→SNS) and therefore must never change shape, never be deprecated,
#: and never return 410 when v0 is sunset. A Stripe-registered webhook URL is a
#: contract with Stripe's infrastructure, not with our frontend; deprecating it
#: would silently stop processing live payments at the v0 sunset date. These are
#: exempt on EVERY mount — the unversioned root alias AND any ``/api/vN/`` mount
#: — so a fragment match short-circuits ``_resolve_deprecation`` before any
#: version resolution. Webhooks are intentionally NOT versioned (Henry, 2026-06):
#: "we shouldn't version the webhooks then".
#:
#: The fragments are matched as substrings of ``request.path``:
#: * ``/webhook``       → …/stripe/webhook/, …/billing/stripe/webhook/,
#:                        …/team/stripe/webhook/, …/methods/webhooks/,
#:                        …/bank/connections/webhooks/plaid/ (substring of "webhooks")
#: * ``/ingest/``       → …/donations/payments/ingest/
#: * ``/email-events/`` → …/content/email-events/ses/, …/workspaces/news/email-events/ses/
_VERSION_STABLE_PATH_MARKERS = (
    "/webhook",
    "/ingest/",
    "/email-events/",
)


def _is_version_stable_path(path: str) -> bool:
    """True iff ``path`` hits an external-system webhook/ingest surface.

    These routes are version-stable by design (registered with Stripe/Plaid/SES),
    so they are exempt from deprecation headers AND from the 410-at-sunset gate on
    every mount. See ``_VERSION_STABLE_PATH_MARKERS``.
    """
    return any(marker in path for marker in _VERSION_STABLE_PATH_MARKERS)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into a **tz-aware** datetime.

    Tolerates a trailing ``Z``. If the source carries no offset, UTC is assumed
    so the result is always tz-aware — callers compare it against an aware
    ``now`` and call ``.timestamp()`` on it, both of which need an unambiguous
    instant. Returning a naive datetime here is what produced the
    ``can't compare offset-naive and offset-aware datetimes`` 500 on every
    ``/api/v0/`` request in prod: ``base.py`` sets ``USE_TZ=False``, so Django's
    ``now`` was naive while this value was aware. The middleware's tests pass
    under ``test.py`` (``USE_TZ=True``), so the gate could not catch it.
    """
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def build_deprecation_headers(entry: dict) -> dict:
    """Build the RFC 9745 / 8594 header set for one config entry.

    Pure function (no request, no settings) so it is directly unit-testable.
    Returns an empty dict if the entry is invalid (missing/garbled dates, or
    ``sunset`` earlier than ``deprecation`` — forbidden by RFC 9745).
    """
    deprecation = _parse_iso(entry.get("deprecation"))
    sunset = _parse_iso(entry.get("sunset"))
    if deprecation is None or sunset is None:
        return {}
    if sunset < deprecation:
        return {}

    headers = {
        # RFC 9745: Deprecation is a structured-field Date — "@" + unix seconds.
        "Deprecation": "@%d" % int(deprecation.timestamp()),
        # RFC 8594: Sunset is an HTTP-date (IMF-fixdate).
        "Sunset": http_date(sunset.timestamp()),
    }
    links = []
    if entry.get("successor"):
        links.append('<%s>; rel="successor-version"' % entry["successor"])
    if entry.get("link"):
        links.append('<%s>; rel="deprecation"' % entry["link"])
    if links:
        headers["Link"] = ", ".join(links)
    return headers


def _sunset_has_passed(entry: dict) -> bool:
    """True iff the entry's ``sunset`` instant is in the past (now >= sunset).

    Drives the 410 enforcement. A missing/garbled sunset returns False (never
    reject on a misconfigured date — fail open, keep serving). Compares against
    an aware UTC ``now`` so the check is well-defined regardless of
    ``settings.USE_TZ`` (``_parse_iso`` always returns aware).
    """
    sunset = _parse_iso(entry.get("sunset"))
    if sunset is None:
        return False
    # Aware UTC now, independent of settings.USE_TZ. _parse_iso always returns
    # aware, so both sides are aware and the comparison is well-defined even
    # when USE_TZ=False (where Django's now() helper is naive).
    return datetime.now(dt_timezone.utc) >= sunset


class ApiDeprecationMiddleware:
    """Stamp deprecation headers on requests to a deprecated API version.

    Covers the explicit ``/api/v0/…`` mount (``version`` URL kwarg) AND the
    unversioned root alias (no kwarg → resolves to ``DEFAULT_VERSION``). Infra
    routes that share the root with the alias are excluded by prefix; the v1
    mount is excluded because its ``version`` kwarg ('v1') isn't in the config.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._maybe_stamp(request, response)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Return 410 Gone once a deprecated version is past its sunset date.

        Runs after URL resolution (so ``resolver_match`` is populated) and
        before the view, so we can short-circuit a sunset version WITHOUT
        running the view. Config-gated: with ``sunset`` in the future this is a
        no-op (the request is served and only gets deprecation headers via
        ``_maybe_stamp``). Once ``now >= sunset`` the deprecated surface returns
        a 410 with the same RFC headers + a JSON body pointing at the migration
        guide — the lossless final step of the §8 lifecycle, so the actual route
        removal needs no code change, just the date passing.
        """
        resolved = self._resolve_deprecation(request)
        if resolved is None:
            return None
        version, entry, headers = resolved
        if not _sunset_has_passed(entry):
            return None  # still within the window — serve + stamp headers.

        body = {
            "error": (
                "This API version (%s) has been retired. Migrate to the "
                "current version (%s)." % (version, entry.get("successor") or "/api/v1/")
            ),
            "error_code": "ApiVersionSunset",
            "migration_guide": entry.get("link"),
            "successor": entry.get("successor"),
        }
        response = JsonResponse(body, status=410)
        for key, value in headers.items():
            response.setdefault(key, value)
        logger.warning(
            "api_sunset_version_rejected version=%s path=%s sunset=%s",
            version, request.path, headers.get("Sunset"),
        )
        return response

    def _maybe_stamp(self, request, response) -> None:
        resolved = self._resolve_deprecation(request)
        if resolved is None:
            return
        version, _entry, headers = resolved
        for key, value in headers.items():
            # Don't clobber a header a view set deliberately.
            response.setdefault(key, value)
        logger.warning(
            "api_deprecated_version_accessed version=%s path=%s sunset=%s",
            version, request.path, headers.get("Sunset"),
        )

    def _resolve_deprecation(self, request):
        """Resolve (version, entry, headers) if this request hits a deprecated
        API surface, else ``None``.

        Shared by ``process_view`` (sunset → 410) and ``_maybe_stamp``
        (in-window → headers) so both apply the identical scope rules: the
        explicit ``/api/vN/`` mount, the unversioned root alias, never v1 /
        infra. Returns ``None`` when the config is empty, the route isn't
        resolved, the version isn't deprecated, or the entry is misconfigured.
        """
        config = getattr(settings, "API_DEPRECATED_VERSIONS", None) or {}
        if not config:
            return None

        # External-system webhook/ingest surfaces (Stripe/Plaid/SES) are
        # version-stable by contract — never deprecate-stamp them, never 410
        # them at sunset, on any mount. Check before version resolution so the
        # exemption holds whether the URL carries a `version` kwarg
        # (/api/v0/…/stripe/webhook/) or rides the unversioned root alias.
        if _is_version_stable_path(request.path):
            return None

        match = getattr(request, "resolver_match", None)
        if match is None:
            return None

        version_param = settings.REST_FRAMEWORK.get("VERSION_PARAM", "version")
        # The explicit /api/vN/ mount captures `version` as a URL kwarg, but
        # StripVersionKwargMiddleware (which runs deeper in the chain, on the
        # request path) pops it out of resolver_match.kwargs and stashes it on
        # the request as `url_path_version` before the view runs. Read the stash
        # first and fall back to the kwarg (covers ordering / schema-generation
        # paths where the stash isn't set).
        version = getattr(request, REQUEST_VERSION_ATTR, None) or match.kwargs.get(version_param)
        if not version:
            # No version anywhere: either the unversioned root-alias API surface
            # (which resolves to DEFAULT_VERSION = 'v0') or a non-API-contract
            # infra route that shares the root. Act on only the former.
            #
            # We derive the alias version from DEFAULT_VERSION rather than
            # `request.version` — the latter lives on the DRF Request wrapper,
            # not the Django request this middleware sees.
            path = request.path
            if path == "/" or path.startswith(_UNVERSIONED_NON_API_PREFIXES):
                # Swagger (''), admin, schema, health, MCP, i18n, static/media.
                return None
            version = settings.REST_FRAMEWORK.get("DEFAULT_VERSION")

        entry = config.get(version)
        if not entry:
            return None

        headers = build_deprecation_headers(entry)
        if not headers:
            logger.warning(
                "api_deprecation_misconfigured version=%s: 'deprecation'/'sunset' "
                "must be ISO-8601 and sunset must be >= deprecation",
                version,
            )
            return None

        return version, entry, headers
