"""Unit tests for the Channels group-name helpers.

The publisher (``ChannelsRealtimeEventAdapter``) and the consumers
(``ResourceStreamConsumer`` / ``WorkspaceActivityConsumer``) both
import these. If either side ever inlines a different format, the
publish lands in a different group than the subscriber joined and
the realtime delivery silently breaks. Tests pin the format down so
that drift fails loudly here instead of at runtime.

Two specific things to guard against:

1. Names use ``[A-Za-z0-9._-]`` only — anything outside that set is
   rejected by ``channels.layers.BaseChannelLayer.valid_group_name``
   in ``channels_redis``. The original ``:`` separator tripped this.
2. The format is byte-identical between producer and consumer.
"""

from __future__ import annotations

# Mirrors channels.layers.BaseChannelLayer.invalid_name_error / valid_group_name.
# We don't import that class directly because Channels initialisation
# pulls in Redis settings; this regex is the documented spec.
import re

import pytest

from infrastructure.realtime.groups import (
    resource_group,
    sponsor_feed_group,
    user_notifications_group,
    workspace_activity_group,
)

_VALID_GROUP_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@pytest.mark.unit
class TestResourceGroup:
    def test_format_is_resource_dot_type_dot_id(self):
        assert resource_group("agent_run", "abc123") == "resource.agent_run.abc123"

    def test_uuid_id_is_returned_verbatim(self):
        # UUIDs are valid in group names — colons in UUIDs would not be,
        # but UUIDs use ``-`` which is in the allowed character set.
        plan_id = "df682b21-1234-5678-90ab-cdef01234567"
        result = resource_group("agent_run", plan_id)
        assert plan_id in result
        assert result == f"resource.agent_run.{plan_id}"

    def test_result_passes_channels_validator(self):
        result = resource_group("agent_run", "df682b21-1234-5678-90ab-cdef01234567")
        assert _VALID_GROUP_NAME.fullmatch(result), (
            f"Group name {result!r} contains characters outside [A-Za-z0-9._-] and would be rejected by Channels Redis."
        )

    def test_underscore_in_resource_type_is_kept(self):
        result = resource_group("document_import", "id1")
        assert result == "resource.document_import.id1"
        assert _VALID_GROUP_NAME.fullmatch(result)


@pytest.mark.unit
class TestWorkspaceActivityGroup:
    def test_format_is_workspace_dot_id_dot_activity(self):
        assert workspace_activity_group("abc123") == "workspace.abc123.activity"

    def test_uuid_workspace_passes_validator(self):
        ws_id = "038d31c8-4564-4db1-a0d7-359509ffa99f"
        result = workspace_activity_group(ws_id)
        assert ws_id in result
        assert _VALID_GROUP_NAME.fullmatch(result), (
            f"Group name {result!r} contains characters outside [A-Za-z0-9._-] and would be rejected by Channels Redis."
        )


@pytest.mark.unit
class TestSponsorFeedGroup:
    def test_format_is_sponsor_dot_user_dot_feed(self):
        assert sponsor_feed_group("u123") == "sponsor.u123.feed"

    def test_uuid_user_passes_validator(self):
        uid = "038d31c8-4564-4db1-a0d7-359509ffa99f"
        result = sponsor_feed_group(uid)
        assert result == f"sponsor.{uid}.feed"
        assert _VALID_GROUP_NAME.fullmatch(result)

    def test_no_colons(self):
        assert ":" not in sponsor_feed_group("abc")


@pytest.mark.unit
class TestUserNotificationsGroup:
    def test_format_is_user_dot_id_dot_notifications(self):
        assert user_notifications_group("u123") == "user.u123.notifications"

    def test_uuid_user_passes_validator(self):
        uid = "038d31c8-4564-4db1-a0d7-359509ffa99f"
        result = user_notifications_group(uid)
        assert result == f"user.{uid}.notifications"
        assert _VALID_GROUP_NAME.fullmatch(result)

    def test_no_colons(self):
        assert ":" not in user_notifications_group("abc")


@pytest.mark.unit
class TestNoColonRegression:
    """Pin the colon-rejection bug so it can't recur silently.

    The pre-fix helpers built ``resource:<type>:<id>`` and
    ``workspace:<id>:activity``. Both contain ``:`` which Channels'
    Redis layer rejects. If anyone reverts to colons, these tests
    fail with a clear message instead of every realtime publish
    silently dying in production.
    """

    def test_resource_group_contains_no_colons(self):
        result = resource_group("agent_run", "abc")
        assert ":" not in result, (
            f"resource_group must not contain ':' characters; Channels Redis rejects them. Got: {result!r}"
        )

    def test_workspace_activity_group_contains_no_colons(self):
        result = workspace_activity_group("abc")
        assert ":" not in result, (
            f"workspace_activity_group must not contain ':' characters; Channels Redis rejects them. Got: {result!r}"
        )


@pytest.mark.unit
class TestConsumersBindGroupHelpers:
    """Regression: the module-level group-helper aliases MUST stay bound.

    2026-07-16 incident — the format hook stripped the
    ``user_notifications_group as _user_notifications_group`` import while
    it was momentarily unused mid-edit; the merged NotificationConsumer
    then crashed with NameError on every /ws/notifications/ connect.
    Import-time syntax checks can't catch a name used only inside an
    async method body, so pin the bindings explicitly.
    """

    def test_consumer_module_binds_all_group_aliases(self):
        from infrastructure.realtime import consumers

        for alias in (
            "_resource_group",
            "_workspace_group",
            "_sponsor_feed_group",
            "_user_notifications_group",
        ):
            assert hasattr(consumers, alias), (
                f"infrastructure.realtime.consumers no longer binds {alias} — "
                "a consumer using it will NameError at websocket connect time."
            )
