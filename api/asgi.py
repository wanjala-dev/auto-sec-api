"""ASGI config — HTTP via Django, WebSocket via Channels.

Daphne is the ASGI server for the demo (parallel service to the
gunicorn HTTP server, see docker-compose). nginx routes ``/ws/*``
to daphne and everything else to gunicorn.

The WebSocket protocol stack:
    - ``JWTAuthMiddlewareStack`` decodes the ``token`` query string
      param, attaches ``scope["user"]``, rejects on invalid.
    - ``URLRouter`` dispatches to the consumer registered for the
      path under ``infrastructure/realtime/routing.py``.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md`` for the broader
design (Phase 7+8).
"""

import os

# Django setup MUST happen before any imports that touch ORM, signals,
# or Channels middleware — the JWT auth middleware below transitively
# imports rest_framework_simplejwt which assumes Django is configured.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings.local")

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from infrastructure.realtime.middleware import JWTAuthMiddlewareStack  # noqa: E402
from infrastructure.realtime.routing import websocket_urlpatterns  # noqa: E402


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
