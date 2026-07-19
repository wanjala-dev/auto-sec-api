"""Scaffold tests for the URL-path API versioning wiring.

These pin the contract of the versioning scaffold (ADR 0006) AND the schema +
MCP cutover that publishes ``/api/v1/`` as the canonical documented surface.

* the explicit ``/api/v0/…`` mount resolves and carries the ``version`` kwarg,
* the unversioned legacy alias still resolves (backward compatibility),
* the FULL surface is mounted under ``/api/v1/`` too — every endpoint (all
  CRUD, every context) resolves there, so a frontend can adopt ``/api/v1/``
  wholesale; reads upgrade their shape when ``request.version == 'v1'``,
* DRF versioning is configured to default unversioned routes to ``v0``
  (runtime DEFAULT_VERSION is unchanged by the cutover),
* the drf-spectacular preprocessing hook now PUBLISHES the ``/api/v1/`` surface:
  it keeps the versioned endpoints and drops the root-alias duplicates,
* operationIds are version-INDEPENDENT (``ContextualAutoSchema.get_operation_id``
  strips the ``(api_)?vN_`` token), so the MCP tool names are byte-identical
  across the cutover.

No DB needed — pure URL resolution + settings + the hook/operationId functions.
"""

from django.urls import resolve

from infrastructure.api.schema import ContextualAutoSchema
from infrastructure.api.schema_hooks import keep_only_canonical_v1_paths


def test_explicit_versioned_route_resolves_with_version_kwarg():
    match = resolve("/api/v0/sectors/")
    assert match.kwargs.get("version") == "v0"


def test_v1_mounts_the_full_surface():
    # Both v0 and v1 mount the WHOLE api surface, so EVERY endpoint resolves
    # under each — nothing 404s under /api/v1/. Un-upgraded reads + all writes
    # pass through with v0 behaviour; migrated reads upgrade via request.version.
    assert resolve("/api/v0/sectors/").kwargs.get("version") == "v0"
    assert resolve("/api/v1/sectors/").kwargs.get("version") == "v1"


def test_v1_migrated_read_resolves_with_version_kwarg():
    # A migrated read is reachable under /api/v1/ with version=v1 (its
    # controller version-selects the v1 serializer on this kwarg).
    match = resolve("/api/v1/sponsorship/donations/my/")
    assert match.kwargs.get("version") == "v1"


def test_unversioned_legacy_route_still_resolves():
    # Backward-compatible alias the current frontend + MCP call. No version
    # kwarg -> DRF falls back to DEFAULT_VERSION ('v0').
    match = resolve("/sectors/")
    assert "version" not in match.kwargs


def test_versioned_and_unversioned_hit_the_same_view():
    assert resolve("/api/v0/sectors/").func == resolve("/sectors/").func


def test_rest_framework_versioning_is_configured(settings):
    rf = settings.REST_FRAMEWORK
    # RequestStashURLPathVersioning reads the version from a request stash set
    # by StripVersionKwargMiddleware, so the full /api/vN/ surface doesn't pass
    # `version=` into rigid view handlers. It is a drop-in URLPathVersioning.
    assert rf["DEFAULT_VERSIONING_CLASS"] == "infrastructure.api.versioning.RequestStashURLPathVersioning"
    assert rf["DEFAULT_VERSION"] == "v0"
    assert "v0" in rf["ALLOWED_VERSIONS"]
    assert rf["VERSION_PARAM"] == "version"


def test_strip_version_kwarg_middleware_is_installed(settings):
    assert "infrastructure.api.versioning.StripVersionKwargMiddleware" in settings.MIDDLEWARE


def test_schema_hook_keeps_v1_and_drops_root_and_v0_aliases():
    # drf-spectacular endpoints: (path, path_regex, method, callback).
    # The cutover hook PUBLISHES the versioned surface: it keeps the
    # /api/(?P<version>vN)/ endpoints (their {version} renders to v1 at
    # generation) and drops the unversioned root aliases. drf-spectacular
    # dedupes the v0 and v1 mounts to a single ^api/(?P<version>v0)/ regex, so
    # there is one versioned twin per endpoint. Infra (/api/schema/) survives.
    endpoints = [
        ("/sectors/", "^sectors/$", "GET", object()),  # root alias — DROP
        ("/api/{version}/sectors/", "^api/(?P<version>v0)/sectors/$", "GET", object()),  # KEEP
        ("/sponsorship/donations/", "^sponsorship/donations/$", "POST", object()),  # root alias — DROP
        ("/api/{version}/sponsorship/donations/", "^api/(?P<version>v0)/sponsorship/donations/$", "POST", object()),  # KEEP
        ("/api/schema/", "^api/schema/$", "GET", object()),  # infra — KEEP
    ]

    kept_paths = [e[0] for e in keep_only_canonical_v1_paths(endpoints)]

    assert kept_paths == [
        "/api/{version}/sectors/",
        "/api/{version}/sponsorship/donations/",
        "/api/schema/",
    ]
    # No bare root-alias context route survives.
    assert "/sectors/" not in kept_paths
    assert "/sponsorship/donations/" not in kept_paths


def test_schema_hook_excludes_endpoint_that_captures_its_own_version_param():
    # An endpoint whose own path captures a `version` param collides with the
    # reserved API VERSION_PARAM: drf-spectacular renders both as {version}, and
    # generation would substitute the API version into the domain param,
    # producing a mangled .../v1/ path. Such endpoints are excluded until the
    # owning context renames the param. Signature: the {version} placeholder
    # appears more than once in the rendered path.
    endpoints = [
        (
            "/api/{version}/grants/{grant_id}/drafts/{version}/",
            "^api/(?P<version>v0)/grants/<str:grant_id>/drafts/<str:version>/",
            "GET",
            object(),
        ),
    ]

    kept_paths = [e[0] for e in keep_only_canonical_v1_paths(endpoints)]

    assert kept_paths == []


_OPERATION_ID_STRIP_CASES = {
    "api_v1_sponsorship_donations_my_retrieve": "sponsorship_donations_my_retrieve",
    "v1_sponsorship_donations_my_retrieve": "sponsorship_donations_my_retrieve",
    "v0_budget_transaction_list": "budget_transaction_list",
    # No version token -> unchanged (the common case once SCHEMA_PATH_PREFIX
    # has already stripped the /api/vN prefix during tokenization).
    "sponsorship_donations_my_retrieve": "sponsorship_donations_my_retrieve",
    # A leading non-version token is NOT stripped.
    "api_health_retrieve": "api_health_retrieve",
    # A `version`-like token mid-id is NOT stripped (only a leading one).
    "grants_drafts_v1_retrieve": "grants_drafts_v1_retrieve",
}


def test_operation_id_strip_regex():
    # The regex backstop that decouples operationIds (hence MCP tool names) from
    # the version path prefix: a leading (api_)?vN_ token is removed so a
    # versioned operation gets the SAME operationId it had at the unversioned
    # root. This is what keeps the MCP tool names byte-identical across the cutover.
    from infrastructure.api.schema import _VERSION_OPERATION_ID_PREFIX

    for raw, expected in _OPERATION_ID_STRIP_CASES.items():
        assert _VERSION_OPERATION_ID_PREFIX.sub("", raw) == expected


def test_get_operation_id_applies_the_strip(monkeypatch):
    # Exercise the override end-to-end: ContextualAutoSchema.get_operation_id
    # delegates to super() then strips the version prefix. Stub the super() call
    # so the test is independent of drf-spectacular's path tokenization.
    schema = ContextualAutoSchema.__new__(ContextualAutoSchema)
    for raw, expected in _OPERATION_ID_STRIP_CASES.items():
        monkeypatch.setattr(
            "drf_spectacular.openapi.AutoSchema.get_operation_id",
            lambda self, _raw=raw: _raw,
        )
        assert schema.get_operation_id() == expected
