"""
OpenAPI schema helpers that add consistent context to every endpoint.
"""
import re
from typing import Any, Dict, List, Optional

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import build_serializer_context
from drf_spectacular.types import OpenApiTypes
from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView

# Leading version token that drf-spectacular derives from the ``/api/vN/`` URL
# prefix when the schema is generated for a versioned surface. The operation at
# ``/api/v1/sponsorship/donations/my/`` tokenizes to a leading version token —
# either ``api_v1_…`` or just ``v1_…`` depending on how much of the ``/api/v1/``
# prefix drf-spectacular's common-path estimation strips (it strips the longest
# shared directory across all published paths; with the v1 cutover that shared
# prefix is ``/api/``, so the surviving token is ``v1_``). We strip the optional
# ``api_`` plus the ``v<N>_`` token so operationIds are version-independent
# regardless of that estimation — see ``ContextualAutoSchema.get_operation_id``.
_VERSION_OPERATION_ID_PREFIX = re.compile(r"^(?:api_)?v\d+_")


class ContextualAutoSchema(AutoSchema):
    """AutoSchema that appends structured context to endpoint descriptions."""

    def get_operation_id(self) -> str:
        """Return a version-independent operationId.

        drf-spectacular derives operationIds from the URL path tokens. When the
        published schema is generated for the canonical ``/api/v1/`` surface
        (see ``infrastructure/api/schema_hooks.py`` +
        ``SpectacularAPIView.api_version``), the version segment leaks into every
        operationId as a leading ``api_v1_`` token — turning today's
        ``sponsorship_donations_my_retrieve`` into
        ``api_v1_sponsorship_donations_my_retrieve``.

        operationIds are load-bearing identity for two downstream consumers:
        the MCP tool surface (tool name == ``sanitize_tool_name(operationId)``,
        ~985 tools) and any generated SDK. Letting the version prefix bleed in
        would rename every MCP tool on a version cutover — a gratuitous breaking
        change for MCP consumers, and churn for SDK users — even though the
        underlying operation is identical.

        Stripping the ``api_v<N>_`` prefix decouples the operationId (hence the
        MCP tool name) from the version path prefix: an operation has the same
        operationId whether it is served at the root, ``/api/v0/``, or
        ``/api/v1/``. The version still lives in the URL path (and in
        ``request.version`` at runtime) — only the operationId is normalised.
        """
        operation_id = super().get_operation_id()
        return _VERSION_OPERATION_ID_PREFIX.sub("", operation_id)

    _SECTION_ORDER = (
        "PURPOSE",
        "CONSTRAINTS",
        "DOES NOT HANDLE",
        "SIDE EFFECTS",
        "AUTH",
        "IDEMPOTENCY",
        "PARSERS",
        "THROTTLES",
        "NOTES",
    )

    def get_description(self) -> str:
        base = super().get_description() or ""
        context = self._render_context()
        if context:
            if base:
                return f"{base}\n\n{context}"
            return context
        return base

    def _render_context(self) -> str:
        context = self._build_context()
        if not context:
            return ""

        sections: List[str] = []
        for title in self._SECTION_ORDER:
            value = context.get(title)
            if not value:
                continue
            sections.append(self._format_section(title, value))

        return "\n\n".join(sections)

    def _build_context(self) -> Dict[str, Any]:
        context: Dict[str, Any] = {}

        explicit = self._get_explicit_context()
        if explicit:
            context.update(explicit)

        if "PURPOSE" not in context:
            purpose = self._default_purpose()
            if purpose:
                context["PURPOSE"] = purpose

        if "AUTH" not in context:
            auth = self._default_auth()
            if auth:
                context["AUTH"] = auth

        if "IDEMPOTENCY" not in context:
            idempotency = self._default_idempotency()
            if idempotency:
                context["IDEMPOTENCY"] = idempotency

        parsers = self._default_parsers()
        if parsers and "PARSERS" not in context:
            context["PARSERS"] = parsers

        throttles = self._default_throttles()
        if throttles and "THROTTLES" not in context:
            context["THROTTLES"] = throttles

        side_effects = self._default_side_effects()
        if side_effects and "SIDE EFFECTS" not in context:
            context["SIDE EFFECTS"] = side_effects

        return context

    def _get_explicit_context(self) -> Dict[str, Any]:
        view = getattr(self, "view", None)
        if not view:
            return {}

        context = getattr(view, "openapi_context", None)
        if not context:
            return {}

        if isinstance(context, str):
            return {"NOTES": context}

        if isinstance(context, dict):
            method = (self.method or "").lower()
            if method and method in context:
                scoped = context.get(method) or {}
                return self._normalize_context(scoped)
            if "default" in context:
                return self._normalize_context(context.get("default") or {})
            return self._normalize_context(context)

        return {}

    def _normalize_context(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        normalized: Dict[str, Any] = {}
        for key, value in data.items():
            if not key:
                continue
            normalized[key.strip().upper().replace("_", " ")] = value
        return normalized

    def _format_section(self, title: str, value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            lines = "\n".join(f"- {item}" for item in value if item)
            return f"{title}:\n{lines}"
        return f"{title}:\n- {value}"

    def _default_purpose(self) -> Optional[str]:
        view = getattr(self, "view", None)
        if not view:
            return None
        try:
            if hasattr(view, "get_view_name"):
                name = view.get_view_name()
                if name:
                    return name
        except AttributeError:
            pass
        return None

    def _default_auth(self) -> Optional[List[str]]:
        view = getattr(self, "view", None)
        if not view:
            return None

        permission_classes = []
        try:
            permission_classes = [perm.__class__.__name__ for perm in view.get_permissions()]
        except Exception:
            permission_classes = [
                perm.__name__ for perm in getattr(view, "permission_classes", []) or []
            ]

        return permission_classes or None

    def _default_idempotency(self) -> Optional[str]:
        method = (self.method or "").upper()
        if method in {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}:
            return "Idempotent by HTTP semantics."
        if method in {"POST", "PATCH"}:
            return "Not idempotent by default."
        return None

    def _default_parsers(self) -> Optional[List[str]]:
        view = getattr(self, "view", None)
        if not view:
            return None
        parser_classes = getattr(view, "parser_classes", []) or []
        names = [parser.__name__ for parser in parser_classes]
        return names or None

    def _default_throttles(self) -> Optional[List[str]]:
        view = getattr(self, "view", None)
        if not view:
            return None
        throttle_classes = getattr(view, "throttle_classes", []) or []
        names = [throttle.__name__ for throttle in throttle_classes]
        return names or None

    def _default_side_effects(self) -> Optional[str]:
        method = (self.method or "").upper()
        if method == "POST":
            return "Creates or triggers a server-side mutation."
        if method in {"PUT", "PATCH"}:
            return "Updates server-side state."
        if method == "DELETE":
            return "Deletes server-side data."
        return None

    def get_request_serializer(self) -> Any:
        """
        Return request body schema for methods that accept a body.

        For safe methods (GET/HEAD/OPTIONS/DELETE), default to no request body
        to avoid misleading schema output when we fall back to a generic object.
        """

        method = (self.method or "").upper()
        if method in {"GET", "HEAD", "OPTIONS", "DELETE"}:
            return None
        return self._get_serializer()

    def _get_serializer(self):  # noqa: D401 - overriding upstream behavior
        """
        Return a serializer (or OpenApiTypes fallback) without emitting schema errors.

        Why:
        - The codebase still contains many APIViews/function views that don't expose
          serializer metadata. drf-spectacular's default behavior logs an error and
          drops those endpoints from the schema, which in turn breaks MCP tool
          discovery that relies on `/api/schema/`.

        Strategy:
        - Attempt the same discovery as drf-spectacular, but if anything is missing
          or raises, fall back to a generic object schema instead of logging and
          ignoring the view.
        """

        view = getattr(self, "view", None)
        if not view:
            return OpenApiTypes.OBJECT

        context = build_serializer_context(view)

        try:
            if isinstance(view, GenericAPIView):
                if view.__class__.get_serializer == GenericAPIView.get_serializer:
                    serializer_class = view.get_serializer_class()
                    if serializer_class:
                        return serializer_class(context=context)
                    return OpenApiTypes.OBJECT
                return view.get_serializer(context=context)

            if isinstance(view, APIView):
                if callable(getattr(view, "get_serializer", None)):
                    return view.get_serializer(context=context)
                if callable(getattr(view, "get_serializer_class", None)):
                    serializer_class = view.get_serializer_class()
                    if serializer_class:
                        return serializer_class(context=context)
                    return OpenApiTypes.OBJECT
                serializer_class = getattr(view, "serializer_class", None)
                if serializer_class:
                    try:
                        return serializer_class(context=context)
                    except TypeError:
                        # Some serializers may not accept context in __init__.
                        return serializer_class
                return OpenApiTypes.OBJECT

        except Exception:
            return OpenApiTypes.OBJECT

        return OpenApiTypes.OBJECT
