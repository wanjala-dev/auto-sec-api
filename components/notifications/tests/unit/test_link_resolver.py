"""Unit coverage for the SOC deep-link resolver.

Pure-function tests — no Django, no DB. The auto-sec frontend is a
single-page HUD, so the route table is deliberately small: an explicit
``deep_link`` wins, workspace-scoped notifications land on
``/ai/v2/<ws>``, and workspace-less notifications get no link.
"""

from __future__ import annotations

from components.notifications.infrastructure.adapters.link_resolver import resolve_link

WS = "11111111-2222-3333-4444-555555555555"


class TestExplicitDeepLinkWins:
    def test_relative_deep_link_wins(self):
        assert (
            resolve_link("ai_event", workspace_id=WS, metadata={"deep_link": "/ai/v2/other?focus=t1"})
            == "/ai/v2/other?focus=t1"
        )

    def test_absolute_deep_link_rejected(self):
        # http(s) origins never pass through — same-origin relative only.
        assert (
            resolve_link("ai_event", workspace_id=WS, metadata={"deep_link": "https://evil.example/x"})
            == f"/ai/v2/{WS}"
        )

    def test_protocol_relative_deep_link_rejected(self):
        assert resolve_link("ai_event", workspace_id=WS, metadata={"deep_link": "//evil.example/x"}) == f"/ai/v2/{WS}"

    def test_share_url_honoured(self):
        assert resolve_link("system", workspace_id=None, metadata={"share": {"url": "/ai/v2/abc"}}) == "/ai/v2/abc"


class TestWorkspaceScopedRoutes:
    def test_ai_event_lands_on_workspace_hud(self):
        assert resolve_link("ai_event", workspace_id=WS) == f"/ai/v2/{WS}"

    def test_system_lands_on_workspace_hud(self):
        assert resolve_link("system", workspace_id=WS) == f"/ai/v2/{WS}"

    def test_message_lands_on_workspace_hud(self):
        assert resolve_link("message", workspace_id=WS) == f"/ai/v2/{WS}"


class TestNoWorkspace:
    def test_no_workspace_no_link(self):
        assert resolve_link("system") is None

    def test_no_workspace_no_metadata_no_link(self):
        assert resolve_link(None, metadata=None) is None
