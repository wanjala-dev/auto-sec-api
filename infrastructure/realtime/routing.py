"""WebSocket URL routing for Channels.

Loaded by ``api/asgi.py``. Each consumer registered here is reachable
at ``/ws/<path>``; the JWT middleware in ``middleware.py`` runs first.
"""

from __future__ import annotations

from django.urls import re_path

from infrastructure.realtime.consumers import (
    NotificationConsumer,
    PingConsumer,
    ResourceStreamConsumer,
    SponsorFeedConsumer,
    WorkspaceActivityConsumer,
)

# UUID pattern matching what Django's URL converter ``<uuid:>`` accepts.
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# Resource type values published today: ``agent_run``, ``document_upload``,
# ``budget_import``, ``income_import``. New types just need a publisher
# call site — no routing change.
_RESOURCE_TYPE = r"[a-z_][a-z0-9_]+"
# Resource ids may be UUIDs (DeepRun.plan_id, Upload.id, …) or short
# tokens (kept lenient so future numeric ids don't require re-routing).
_RESOURCE_ID = r"[A-Za-z0-9_\-]+"


websocket_urlpatterns = [
    re_path(r"^ws/ping/$", PingConsumer.as_asgi()),
    # Per-user notification stream — no ids in the path; scoped to the
    # authenticated user inside the consumer (badge + feed live updates).
    re_path(r"^ws/notifications/$", NotificationConsumer.as_asgi()),
    # Donor-private transparency feed — no workspace in the path; scoped to
    # the authenticated user inside the consumer.
    re_path(r"^ws/sponsor/feed/$", SponsorFeedConsumer.as_asgi()),
    re_path(
        rf"^ws/workspaces/(?P<workspace_id>{_UUID})/activity/$",
        WorkspaceActivityConsumer.as_asgi(),
    ),
    re_path(
        rf"^ws/workspaces/(?P<workspace_id>{_UUID})/resources/"
        rf"(?P<resource_type>{_RESOURCE_TYPE})/"
        rf"(?P<resource_id>{_RESOURCE_ID})/$",
        ResourceStreamConsumer.as_asgi(),
    ),
]
