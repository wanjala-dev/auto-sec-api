"""drf-spectacular preprocessing hooks for the API versioning cutover.

The public API surface is mounted three ways (see ``api/urls.py``):

* at the root (``/sponsorship/…``) — the backward-compatible alias that
  legacy callers still hit; resolves to ``request.version == 'v0'`` via
  ``DEFAULT_VERSION`` at runtime.
* under ``/api/(?P<version>v0)/…`` and ``/api/(?P<version>v1)/…`` — the
  explicitly-versioned surface. drf-spectacular's enumerator renders both
  versioned mounts as the SAME templated path (``/api/{version}/…``) and
  deduplicates them, so the raw endpoint list contains, for each operation,
  exactly one root alias plus one ``/api/{version}/…`` twin.

**The cutover (this hook).** ``/api/v1/`` is now the *canonical, published*
surface. This hook keeps the versioned (``/api/{version}/…``) endpoints and
drops the root-alias duplicates, leaving exactly ONE operation per endpoint.
The schema view is configured to generate with ``api_version='v1'`` (see
``infrastructure/api/schema.py::V1SpectacularAPIView`` wiring in
``api/urls.py``), so drf-spectacular's ``modify_for_versioning`` substitutes
``{version}`` → ``v1`` and the served schema / Swagger / Redoc / MCP surface
all advertise ``/api/v1/…`` paths.

**Why this runs at preprocessing (on the endpoint list), not postprocessing
(on the rendered schema).** operationIds are derived from the path during
``get_operation`` — which happens AFTER this hook but BEFORE path
substitution. Dropping the root aliases here, before operationId generation,
prevents an operationId collision: the root alias would generate
``sponsorship_donations_my_retrieve`` and the ``/api/v1/`` twin generates
``api_v1_sponsorship_donations_my_retrieve`` (then normalised back to the
un-prefixed form by ``ContextualAutoSchema.get_operation_id``). If both
survived, drf-spectacular would see two operations resolving to the same
operationId and warn / clobber. One operation per endpoint, picked here.

Keeping the whole policy in one tiny, well-named function is the point: a
future re-pin (e.g. publishing ``/api/v2/`` as canonical) is a one-line change.
"""

import re

from django.conf import settings as _django_settings


def _version_param() -> str:
    return _django_settings.REST_FRAMEWORK.get("VERSION_PARAM", "version")


def _api_version_mount_re() -> "re.Pattern[str]":
    """Regex that matches ONLY the ``^api/(?P<version>vN)/`` versioned mount.

    Anchoring to the ``api/`` prefix + a ``v``-led version capture is what
    disambiguates the API-version mount from an unrelated path parameter that
    merely happens to be named ``version``. For example the grants route
    ``grants/<str:grant_id>/drafts/<str:version>/`` (a grant-draft revision
    number) renders a ``{version}`` path variable too — but it is NOT an API
    version mount and must NOT be treated as one. Keying off the precise
    ``^api/(?P<version>v`` regex shape avoids that false positive.
    """
    return re.compile(rf"\^?api/\(\?P<{re.escape(_version_param())}>v")


def _is_api_version_mount(path_regex: str) -> bool:
    """True iff this endpoint is one of the ``/api/(?P<version>vN)/…`` mounts."""
    return bool(_api_version_mount_re().search(path_regex))


def _collides_with_version_param(path: str) -> bool:
    """True iff the endpoint captures its OWN ``version`` path param.

    drf-spectacular renders the API version segment AND a same-named domain path
    param as the same ``{version}`` placeholder, so a colliding endpoint shows
    the placeholder more than once (one from the ``/api/{version}/`` mount, one
    from its own capture). At generation time ``modify_for_versioning`` does a
    blanket ``uritemplate.partial(path, {version_param: 'v1'})`` and so
    OVERWRITES the domain param with the API version literal — turning
    ``/api/v1/grants/{grant_id}/drafts/{version}/`` into
    ``…/drafts/v1/``, which is wrong (the draft-revision value is gone).

    Such an endpoint is structurally unrepresentable under ``/api/vN/`` until the
    owning context renames its path param off the reserved ``VERSION_PARAM``
    name. We exclude it from the versioned schema rather than publish a mangled
    path. Exactly one endpoint hits this today —
    ``GET /grants/{grant_id}/drafts/{version}/`` — and it was already absent from
    the published schema before the cutover, so excluding it keeps the surface
    byte-identical. TODO(grants): rename that param (e.g. ``draft_version``) so
    the endpoint can be published; tracked as a grants-context follow-up.
    """
    placeholder = f"{{{_version_param()}}}"
    return path.count(placeholder) > 1


def keep_only_canonical_v1_paths(endpoints):
    """Publish ``/api/v1/`` as canonical: keep versioned endpoints, drop root aliases.

    ``endpoints`` is drf-spectacular's list of
    ``(path, path_regex, method, callback)`` tuples. We keep:

    * every versioned endpoint (``/api/{version}/…`` — carries the version
      capture group); generation with ``api_version='v1'`` turns these into
      ``/api/v1/…``. **Except** endpoints that capture their own ``version``
      path param (``_collides_with_version_param``): those would render a
      mangled ``…/v1/…`` path, so they are excluded until the owning context
      renames the param.
    * every ``/api/``-prefixed infra endpoint (``/api/schema/``,
      ``/api/health/`` …) — these have no versioned twin and are not part of
      the public, versioned contract, so they stay root-mounted.

    We drop the root-alias context routes (``/sponsorship/…`` etc.) — the
    unversioned duplicates of the versioned endpoints — so the published schema
    carries exactly one operation per endpoint, under ``/api/v1/``.
    """
    kept = []
    for endpoint in endpoints:
        path, path_regex = endpoint[0], endpoint[1]
        if _is_api_version_mount(path_regex):
            if _collides_with_version_param(path):
                continue  # unrepresentable under /api/vN/ — see helper docstring
            kept.append(endpoint)
        elif path.startswith("/api/"):
            kept.append(endpoint)  # infra (schema/health) — root-mounted, kept
        # else: root-alias context route — dropped (its /api/v1/ twin is kept)
    return kept
