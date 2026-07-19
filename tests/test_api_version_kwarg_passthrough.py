"""The full /api/vN/ surface must not 500 on rigid view handler signatures.

The public surface is mounted under the root alias, /api/v0/, AND /api/v1/.
DRF's stock URLPathVersioning would pass the captured ``version`` URL kwarg
straight into every view handler, so any custom ``APIView`` method with a rigid
signature (``def get(self, request, country=None):``) would 500 with
``TypeError: get() got an unexpected keyword argument 'version'`` when hit via
``/api/v0/`` or ``/api/v1/``.

StripVersionKwargMiddleware (pops the kwarg, stashes it) +
RequestStashURLPathVersioning (reads it from the stash) fix this centrally, so
every endpoint — reads and writes, every context — functions under the
versioned mounts without each view needing ``**kwargs``.

These tests exercise both the unit pieces and the real HTTP path through a
known rigid-signature public endpoint (``/countries/`` -> ``CountryAll.get``).
"""

from types import SimpleNamespace

import pytest
from django.test import Client

from infrastructure.api.versioning import (
    REQUEST_VERSION_ATTR,
    RequestStashURLPathVersioning,
    StripVersionKwargMiddleware,
)


# ── Unit: middleware pops the kwarg + stashes it ─────────────────────────────


def test_middleware_pops_version_kwarg_and_stashes_it():
    request = SimpleNamespace()
    middleware = StripVersionKwargMiddleware(get_response=lambda r: r)
    view_kwargs = {"version": "v1", "country": "KE"}

    middleware.process_view(request, view_func=None, view_args=(), view_kwargs=view_kwargs)

    # version is removed from what the view receives, stashed on the request.
    assert "version" not in view_kwargs
    assert view_kwargs == {"country": "KE"}
    assert getattr(request, REQUEST_VERSION_ATTR) == "v1"


def test_middleware_no_version_kwarg_is_a_noop():
    request = SimpleNamespace()
    middleware = StripVersionKwargMiddleware(get_response=lambda r: r)
    view_kwargs = {"country": "KE"}

    middleware.process_view(request, view_func=None, view_args=(), view_kwargs=view_kwargs)

    assert view_kwargs == {"country": "KE"}
    assert not hasattr(request, REQUEST_VERSION_ATTR)


# ── Unit: scheme reads the stash, defaults, and rejects bad versions ─────────


def _drf_request(stashed_version):
    # determine_version reads getattr(request, REQUEST_VERSION_ATTR, None).
    req = SimpleNamespace()
    if stashed_version is not None:
        setattr(req, REQUEST_VERSION_ATTR, stashed_version)
    return req


def test_scheme_reads_stashed_version():
    scheme = RequestStashURLPathVersioning()
    assert scheme.determine_version(_drf_request("v1")) == "v1"
    assert scheme.determine_version(_drf_request("v0")) == "v0"


def test_scheme_falls_back_to_default_when_unstashed():
    # Root alias: no version stashed -> DEFAULT_VERSION ('v0').
    scheme = RequestStashURLPathVersioning()
    assert scheme.determine_version(_drf_request(None)) == "v0"


def test_scheme_rejects_disallowed_version():
    from rest_framework import exceptions

    scheme = RequestStashURLPathVersioning()
    with pytest.raises(exceptions.NotFound):
        scheme.determine_version(_drf_request("v9"))


# ── Integration: a rigid-signature handler no longer 500s under /api/vN/ ─────


@pytest.mark.django_db
class TestRigidHandlerSurvivesVersionedMounts:
    """`/countries/` -> CountryAll.get(self, request) has no **kwargs.

    Before the fix it 500'd under /api/v0/ and /api/v1/ with the version
    TypeError; the root alias worked. After the fix all three behave the same.
    """

    def test_root_alias_works(self):
        assert Client().get("/countries/").status_code == 200

    def test_v0_mount_does_not_500(self):
        assert Client().get("/api/v0/countries/").status_code == 200

    def test_v1_mount_does_not_500(self):
        assert Client().get("/api/v1/countries/").status_code == 200

    def test_all_three_mounts_return_identical_body(self):
        # countries carry no money/datetime, so v0 and v1 shapes are identical;
        # this proves the version kwarg passthrough doesn't perturb the payload.
        root = Client().get("/countries/")
        v0 = Client().get("/api/v0/countries/")
        v1 = Client().get("/api/v1/countries/")
        assert root.content == v0.content == v1.content
