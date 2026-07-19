"""WebSocket JWT authentication middleware for Channels.

The frontend opens ``wss://api.wanjala.art/ws/...?token=<jwt>`` — this
middleware decodes the token on connection, looks up the user, and
attaches them to ``scope["user"]``. Connections without a valid token
get an anonymous user; consumers reject those.

The ``token`` is a query string param because JS WebSocket doesn't
expose a way to set custom headers on connection. Same convention
django-channels-jwt-auth-middleware uses.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md`` Phase 7.0.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


def _resolve_user_from_token_sync(raw_token: str):
    """Sync helper that does the JWT decode + user lookup. Exposed
    separately from the async wrapper below so tests can assert against
    it without going through ``async_to_sync`` (which trips on the
    test DB connection lifecycle)."""
    try:
        from rest_framework_simplejwt.authentication import JWTAuthentication
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    except ImportError:
        return AnonymousUser()

    auth = JWTAuthentication()
    try:
        validated = auth.get_validated_token(raw_token)
        user = auth.get_user(validated)
    except (InvalidToken, TokenError) as exc:
        logger.info("ws_jwt_invalid token=%s reason=%s", raw_token[:8], exc)
        return AnonymousUser()
    except Exception:  # noqa: BLE001
        # Don't leak details — anonymous user fails the consumer's
        # authenticated guard the same way an invalid token does.
        logger.exception("ws_jwt_decode_failed")
        return AnonymousUser()
    return user


@database_sync_to_async
def _resolve_user_from_token(raw_token: str):
    """Async-friendly wrapper used by the Channels middleware. Calls
    the sync helper inside ``database_sync_to_async`` so the DB
    lookup happens on a thread the connection pool understands."""
    return _resolve_user_from_token_sync(raw_token)


class JWTAuthMiddleware(BaseMiddleware):
    """Read ``token`` from the WebSocket connection query string and
    attach the matching user to ``scope["user"]``."""

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"") or b""
        if isinstance(query_string, bytes):
            query_string = query_string.decode("utf-8", errors="ignore")
        params = parse_qs(query_string)
        raw_tokens = params.get("token") or params.get("access_token") or []
        raw_token = raw_tokens[0].strip() if raw_tokens else ""
        if raw_token:
            scope["user"] = await _resolve_user_from_token(raw_token)
        else:
            scope["user"] = AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """Stack used by ``api/asgi.py``: try the JWT token first, fall
    back to the standard cookie/session-based AuthMiddleware so other
    auth flows (e.g. dev sessions) keep working."""
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
