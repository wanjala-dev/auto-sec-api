"""Unit matrix for the per-channel delivery gate (pure domain policy)."""

from __future__ import annotations

import pytest

from components.notifications.domain.enums import DeliveryChannel, NotificationType
from components.notifications.domain.policies.delivery_channel_policy import (
    EMAIL_WORTHY_TYPES,
    is_email_worthy,
    resolve_enabled_channels,
)

pytestmark = pytest.mark.unit


class TestResolveEnabledChannels:
    def test_both_off_realtime_only(self):
        channels = resolve_enabled_channels(push_enabled=False, email_enabled=False)
        assert channels == (DeliveryChannel.REALTIME,)

    def test_push_on_email_off(self):
        channels = resolve_enabled_channels(push_enabled=True, email_enabled=False)
        assert channels == (DeliveryChannel.REALTIME, DeliveryChannel.WEB_PUSH)

    def test_push_off_email_on(self):
        channels = resolve_enabled_channels(push_enabled=False, email_enabled=True)
        assert channels == (DeliveryChannel.REALTIME, DeliveryChannel.EMAIL)

    def test_both_on(self):
        channels = resolve_enabled_channels(push_enabled=True, email_enabled=True)
        assert channels == (
            DeliveryChannel.REALTIME,
            DeliveryChannel.WEB_PUSH,
            DeliveryChannel.EMAIL,
        )

    @pytest.mark.parametrize("push", [True, False])
    @pytest.mark.parametrize("email", [True, False])
    def test_realtime_is_always_first_and_always_present(self, push, email):
        channels = resolve_enabled_channels(push_enabled=push, email_enabled=email)
        assert channels[0] is DeliveryChannel.REALTIME
        assert (DeliveryChannel.WEB_PUSH in channels) is push
        assert (DeliveryChannel.EMAIL in channels) is email


class TestEmailWorthyTypes:
    """T1-S8 — email is reserved for high-value notification types."""

    def test_policy_is_exactly_the_high_value_set(self):
        assert (
            frozenset(
                {
                    NotificationType.MESSAGE,
                    NotificationType.MENTION,
                    NotificationType.REPORT,
                    NotificationType.SYSTEM,
                }
            )
            == EMAIL_WORTHY_TYPES
        )

    @pytest.mark.parametrize(
        "worthy",
        [
            NotificationType.MESSAGE,
            NotificationType.MENTION,
            NotificationType.REPORT,
            NotificationType.SYSTEM,
        ],
    )
    def test_high_value_types_are_email_worthy(self, worthy):
        assert is_email_worthy(worthy.value) is True

    @pytest.mark.parametrize(
        "unworthy",
        [
            NotificationType.LIKE,
            NotificationType.COMMENT,
            NotificationType.FOLLOW,
            NotificationType.AI_EVENT,
        ],
    )
    def test_ambient_types_are_not_email_worthy(self, unworthy):
        assert is_email_worthy(unworthy.value) is False

    def test_unknown_type_is_not_email_worthy(self):
        assert is_email_worthy("not_a_real_type") is False

    def test_every_enum_member_has_an_explicit_decision(self):
        """Adding a NotificationType forces a conscious email-worthiness call —
        the sets must partition the enum, no accidental drift."""
        worthy = {t for t in NotificationType if is_email_worthy(t.value)}
        assert worthy == EMAIL_WORTHY_TYPES
        assert worthy | {t for t in NotificationType if not is_email_worthy(t.value)} == set(NotificationType)
