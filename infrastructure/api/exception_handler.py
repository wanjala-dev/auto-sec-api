"""Unified DRF exception handler that maps domain errors to HTTP responses.

Catches the shared_kernel error taxonomy (DomainError, ValidationError,
NotFoundError, etc.) and converts them to consistent JSON responses with
appropriate HTTP status codes. Falls through to DRF's default handler for
everything else (auth errors, serializer validation, throttling, etc.).

Wired via ``REST_FRAMEWORK["EXCEPTION_HANDLER"]`` in settings.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    DomainError,
    IntegrationError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger("api.exceptions")


def custom_exception_handler(exc, context):
    """Map domain errors to HTTP responses.

    Priority order (most specific first):
    1. DRF-native errors → delegate to DRF default handler
    2. NotFoundError → 404
    3. ConflictError → 409
    4. ValidationError → 400
    5. AuthorizationError → 403
    6. ConfigurationError → 503
    7. IntegrationError → 502
    8. DomainError (catch-all) → 400
    9. Unhandled → let DRF return 500 (or None so Django handles it)
    """
    # Let DRF handle its own exceptions first (auth, throttle, parse errors, etc.)
    response = drf_default_handler(exc, context)
    if response is not None:
        return response

    # Map domain errors to HTTP responses
    if isinstance(exc, NotFoundError):
        return _error_response(exc, status.HTTP_404_NOT_FOUND, context)

    if isinstance(exc, ConflictError):
        return _error_response(exc, status.HTTP_409_CONFLICT, context)

    if isinstance(exc, ValidationError):
        return _error_response(exc, status.HTTP_400_BAD_REQUEST, context)

    if isinstance(exc, AuthorizationError):
        return _error_response(exc, status.HTTP_403_FORBIDDEN, context)

    if isinstance(exc, ConfigurationError):
        logger.error("Configuration error: %s", exc, exc_info=True)
        return _error_response(exc, status.HTTP_503_SERVICE_UNAVAILABLE, context)

    if isinstance(exc, IntegrationError):
        logger.warning("Integration error: %s (service=%s)", exc, getattr(exc, "service", None))
        return _error_response(exc, status.HTTP_502_BAD_GATEWAY, context)

    if isinstance(exc, DomainError):
        return _error_response(exc, status.HTTP_400_BAD_REQUEST, context)

    # Not a domain error — return None so Django's default 500 handling kicks in.
    return None


def _error_response(exc, status_code, context):
    """Build a consistent error JSON response."""
    view = context.get("view")
    view_name = type(view).__name__ if view else "unknown"

    body = {
        "error": _extract_message(exc),
        "error_code": type(exc).__name__,
    }

    # Errors that declare a stable machine code (class attr ``code``) also get
    # the DRF-shaped ``detail`` + ``code`` keys so clients can branch on a
    # contract string instead of a Python class name (e.g. the org audit-log
    # toggle's ``org_audit_log_disabled`` → frontend renders a "turned off"
    # state, not a generic permission error).
    machine_code = getattr(exc, "code", None)
    if isinstance(machine_code, str) and machine_code:
        body["code"] = machine_code
        body["detail"] = body["error"]

    if status_code >= 500:
        logger.error(
            "api_error status=%d view=%s error=%s",
            status_code,
            view_name,
            exc,
            exc_info=True,
        )
    else:
        logger.info(
            "api_error status=%d view=%s error=%s error_code=%s",
            status_code,
            view_name,
            exc,
            type(exc).__name__,
        )

    return Response(body, status=status_code)


def _extract_message(exc):
    """Get a clean user-facing message from an exception."""
    msg = str(exc).strip()
    if not msg:
        msg = type(exc).__name__
    return msg
