"""URL-path API versioning that does not leak the ``version`` kwarg into views.

The public API surface is mounted three ways (see ``api/urls.py``):

* the root alias (``/sponsorship/…``)         — no ``version`` kwarg, resolves to v0
* ``/api/(?P<version>v0)/sponsorship/…``       — explicit v0
* ``/api/(?P<version>v1)/sponsorship/…``       — explicit v1

DRF's stock :class:`rest_framework.versioning.URLPathVersioning` reads the
``version`` value out of the **view kwargs**. Django passes those same captured
URL kwargs straight to the view handler, so the *full* surface mounted under
``/api/vN/`` would call every handler with an extra ``version='v1'`` keyword.
Any custom ``APIView`` handler with a rigid signature
(``def get(self, request, workspace_id):``) — and there are many across the
contexts — then raises ``TypeError: get() got an unexpected keyword argument
'version'`` and 500s. Only DRF generics (which already take ``**kwargs``) survive.

The root fix is to stop the kwarg from ever reaching the handler:

* :class:`StripVersionKwargMiddleware` runs in ``process_view`` (before the view
  is called), pops ``version`` out of the captured URL kwargs, and stashes it on
  the request as ``request.url_path_version``.
* :class:`RequestStashURLPathVersioning` reads the version from that stash
  instead of from the (now-cleaned) view kwargs.

Net effect: every endpoint — reads and writes, every context — functions under
``/api/v1/`` and ``/api/v0/`` without each view needing ``**kwargs``, and new
views can't silently regress. ``request.version`` is still set exactly as
before, so the per-context ``serializer_for_version(request.version)`` upgrades
are unaffected. The ``(?P<version>…)`` named groups stay in the URLconf, so
``request.versioning_scheme.reverse(...)`` continues to work.

See ADR 0006 + the ``api-versioning`` skill.
"""

from __future__ import annotations

from rest_framework import exceptions
from rest_framework.settings import api_settings
from rest_framework.versioning import URLPathVersioning

#: Attribute name used to carry the resolved URL-path version across the
#: middleware → versioning-scheme boundary on the request object.
REQUEST_VERSION_ATTR = "url_path_version"


class StripVersionKwargMiddleware:
    """Pop the URL-path ``version`` kwarg before it reaches the view handler.

    Implemented as ``process_view`` so it runs after URL resolution (the
    ``version`` group is captured) but before the view is invoked — the exact
    window in which Django decides which kwargs to hand the view. We move the
    value onto the request so :class:`RequestStashURLPathVersioning` can still
    read it, then drop it from ``view_kwargs`` so rigid handler signatures don't
    blow up.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):  # noqa: D401
        version_param = api_settings.VERSION_PARAM
        if version_param in view_kwargs:
            setattr(request, REQUEST_VERSION_ATTR, view_kwargs.pop(version_param))
        return None


class RequestStashURLPathVersioning(URLPathVersioning):
    """URLPathVersioning that reads the version from the request stash.

    Behaviour is identical to the stock scheme (validates against
    ``ALLOWED_VERSIONS``, falls back to ``DEFAULT_VERSION``, raises ``NotFound``
    for a disallowed version, supports ``reverse()`` via the named URL group) —
    it just sources the version from ``request.url_path_version`` (set by
    :class:`StripVersionKwargMiddleware`) instead of from the view kwargs, which
    the middleware has already emptied of the ``version`` key.
    """

    def determine_version(self, request, *args, **kwargs):
        version = getattr(request, REQUEST_VERSION_ATTR, None)
        if version is None:
            # Fallback to the URL ``version`` kwarg (stock URLPathVersioning
            # behaviour). At runtime this is normally absent — the middleware
            # has already popped it into the stash — so the stash above wins.
            # It matters for drf-spectacular schema generation: that pipeline
            # has no middleware and emulates a versioned request by injecting
            # ``view.kwargs[version_param]`` (see
            # ``drf_spectacular.plumbing.modify_for_versioning``). Reading the
            # kwarg here lets ``operation_matches_version`` resolve the
            # generated version correctly so the schema can be rendered for a
            # chosen ``/api/vN/`` surface. Without it, generation always falls
            # back to ``default_version`` and a request for ``v1`` matches
            # nothing.
            version = kwargs.get(self.version_param)
        if version is None:
            version = self.default_version
        if not self.is_allowed_version(version):
            raise exceptions.NotFound(self.invalid_version_message)
        return version
