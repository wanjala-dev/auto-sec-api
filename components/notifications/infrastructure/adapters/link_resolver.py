"""Deep-link resolver — map a dispatched notification to a frontend route.

``resolve_link()`` turns (notification_type, target, workspace, metadata)
into a RELATIVE frontend path stored in ``metadata["link"]`` by
``dispatch_notification_async`` so the in-app row, the realtime WS
envelope, and the web-push payload all carry the same destination.

Paths are relative on purpose: the frontend origin differs per
environment, so the API layer never bakes an origin in. Layers that need
an absolute URL (web push, email) absolutize with
``resolve_frontend_base_url()`` at send time.

Auto-sec's frontend is a single-page HUD (the Command Center) — the
route table (``auto-sec-frontend/src/root/presentation/App.jsx``) is:

    /ai/v2/<ws>     the workspace Command Center HUD (everything lives here)
    /ai/v2          the HUD without a workspace pinned
    /               root (redirects into the HUD)

So every workspace-scoped notification deep-links into the workspace HUD;
a context that already computed a more specific ``metadata["deep_link"]``
always wins.

Pure function: no ORM queries, no Django imports. The ``target`` is only
inspected via ``_meta.app_label`` / ``_meta.model_name`` / ``pk``.
"""

from __future__ import annotations

__all__ = ["resolve_link"]


def _is_relative_path(value: object) -> bool:
    """Accept only same-origin absolute paths (``/…``, not ``//…`` or ``http…``)."""
    return isinstance(value, str) and value.startswith("/") and not value.startswith("//")


def resolve_link(
    notification_type: str | None,
    target=None,
    workspace_id: str | None = None,
    metadata: dict | None = None,
) -> str | None:
    """Resolve the frontend route for a notification. Returns ``None`` when
    no sensible destination exists (no workspace and no explicit deep link)."""
    metadata = metadata or {}
    ws = str(workspace_id) if workspace_id else None

    # 1. A context that already built a deep link wins (DRY — don't re-derive).
    deep_link = metadata.get("deep_link")
    if _is_relative_path(deep_link):
        return deep_link
    share = metadata.get("share")
    if isinstance(share, dict) and _is_relative_path(share.get("url")):
        return share["url"]

    # 2. Everything workspace-scoped lands on the workspace Command Center
    # HUD — findings, sign-off escalations, AI events, kill-switch notices,
    # draft-PR reviews all surface there.
    if ws:
        return f"/ai/v2/{ws}"

    # 3. No workspace → no sensible destination (the HUD without a workspace
    # can't focus anything; pushing users to the bare root adds no value).
    return None
