"""Versioned OpenAPI schema views.

Lives separately from ``infrastructure/api/schema.py`` (which holds
``ContextualAutoSchema``, the project's ``DEFAULT_SCHEMA_CLASS``) on purpose:
importing ``drf_spectacular.views.SpectacularAPIView`` triggers its
``@extend_schema`` decorator, which resolves ``DEFAULT_SCHEMA_CLASS`` →
``infrastructure.api.schema.ContextualAutoSchema``. If this view class were
declared in ``schema.py`` itself, that resolution would fire mid-import (before
``ContextualAutoSchema`` is defined) and crash with a circular-import error.
Keeping the view in its own module breaks the cycle.
"""

from drf_spectacular.views import SpectacularAPIView


class V1SpectacularAPIView(SpectacularAPIView):
    """Schema view that generates the canonical ``/api/v1/`` surface.

    Setting ``api_version`` is drf-spectacular's supported, per-view mechanism
    for pinning the generated version:
    ``SpectacularAPIView._get_schema_response`` reads ``self.api_version`` (it
    takes precedence over ``request.version``) and hands it to the
    ``SchemaGenerator``, which sets ``request.version`` for generation and
    drives ``modify_for_versioning`` to substitute ``{version}`` → ``v1`` in
    every versioned path. The runtime ``DEFAULT_VERSION`` ('v0') is untouched —
    this only affects schema *generation*, not request dispatch, and nothing is
    mutated at the settings/global level.

    Swagger and Redoc reference this view by ``url_name='schema'``, so they
    render the same v1 schema; the MCP surface fetches ``/api/schema/`` and
    therefore also sees v1 — all without renaming any operationId / MCP tool
    (the ``api_v1_`` token is stripped by
    ``ContextualAutoSchema.get_operation_id``).
    """

    api_version = "v1"
