"""Unit tests for feature-flag workspace resolution precedence.

The load-bearing rule under test: when a view exposes a resource-scoped
``get_feature_flag_workspace_id`` hook, the flag MUST be evaluated against the
resource's workspace, NOT the user's active workspace. The AI-writing
``draft-with-ai`` bug was exactly this — a member acting on a draft in
workspace B got the flag evaluated against their active workspace A (which
lacked the Pro gate) and was silently 403'd.
"""

from __future__ import annotations

import pytest

from components.shared_platform.infrastructure.services.feature_flags import (
    resolve_workspace_id_from_request,
)

pytestmark = pytest.mark.unit

WS_URL = "11111111-1111-1111-1111-111111111111"
WS_QUERY = "22222222-2222-2222-2222-222222222222"
WS_RESOURCE = "33333333-3333-3333-3333-333333333333"
WS_ACTIVE = "44444444-4444-4444-4444-444444444444"


class _Profile:
    def __init__(self, active_workspace_id):
        self.active_workspace_id = active_workspace_id


class _User:
    def __init__(self, active_workspace_id=None, authenticated=True):
        self.is_authenticated = authenticated
        self.profile = _Profile(active_workspace_id) if active_workspace_id else None


class _Request:
    def __init__(self, user=None, query_params=None):
        self.user = user
        self.query_params = query_params or {}


class _View:
    def __init__(self, kwargs=None, resource_ws=None):
        self.kwargs = kwargs or {}
        self._resource_ws = resource_ws

    # Only present when resource_ws is supplied — mirrors the real views that
    # define get_feature_flag_workspace_id only when they own a resource.
    def get_feature_flag_workspace_id(self, request):  # noqa: D401
        return self._resource_ws


def test_url_kwarg_wins_over_everything():
    request = _Request(user=_User(active_workspace_id=WS_ACTIVE))
    view = _View(kwargs={"workspace_id": WS_URL}, resource_ws=WS_RESOURCE)
    assert resolve_workspace_id_from_request(request, view=view) == WS_URL


def test_query_param_wins_over_resource_and_active():
    request = _Request(
        user=_User(active_workspace_id=WS_ACTIVE),
        query_params={"workspace_id": WS_QUERY},
    )
    view = _View(resource_ws=WS_RESOURCE)
    assert resolve_workspace_id_from_request(request, view=view) == WS_QUERY


def test_resource_hook_wins_over_active_workspace():
    """The core regression guard: resource workspace beats active workspace."""
    request = _Request(user=_User(active_workspace_id=WS_ACTIVE))
    view = _View(resource_ws=WS_RESOURCE)
    assert resolve_workspace_id_from_request(request, view=view) == WS_RESOURCE


def test_falls_back_to_active_workspace_when_no_resource_hook():
    request = _Request(user=_User(active_workspace_id=WS_ACTIVE))
    view = _View()  # no get_feature_flag_workspace_id
    assert resolve_workspace_id_from_request(request, view=view) == WS_ACTIVE


def test_falls_back_to_active_when_resource_hook_returns_none():
    """A draft that doesn't exist yet (hook returns None) still resolves to the
    active workspace rather than crashing — the hook is additive, not required.
    """
    request = _Request(user=_User(active_workspace_id=WS_ACTIVE))
    view = _View(resource_ws=None)
    assert resolve_workspace_id_from_request(request, view=view) == WS_ACTIVE


def test_returns_none_when_nothing_resolves():
    request = _Request(user=_User(authenticated=False))
    view = _View()
    assert resolve_workspace_id_from_request(request, view=view) is None
