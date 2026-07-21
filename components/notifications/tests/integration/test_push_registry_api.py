"""Integration tests for the push device registry endpoints (T1-S5).

POST /notifications/push/subscriptions/   — upsert by endpoint hash
DELETE /notifications/push/subscriptions/ — idempotent revoke (always 204)
GET /notifications/push/vapid-public-key/ — env-driven VAPID public key
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from components.notifications.domain.value_objects.push_endpoint import derive_endpoint_hash
from components.notifications.infrastructure.repositories.orm_push_subscription_repository import (
    OrmPushSubscriptionRepository,
)
from infrastructure.persistence.notifications.models import (
    Notification,
    NotificationDelivery,
    PushSubscription,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

ENDPOINT = "https://push.example.com/send/device-token-1"
WEB_KEYS = {"p256dh": "BPubKey", "auth": "authsecret"}


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _subscribe(client, **overrides):
    payload = {"endpoint": ENDPOINT, "keys": WEB_KEYS, "device_label": "MacBook"}
    payload.update(overrides)
    return client.post(reverse("notifications:push-subscriptions"), payload, format="json")


class TestSubscribe:
    def test_subscribe_creates_row(self, user_factory):
        user = user_factory()
        response = _subscribe(_client(user))

        assert response.status_code == 201
        subscription = PushSubscription.objects.get(user=user)
        assert subscription.endpoint == ENDPOINT
        assert subscription.endpoint_hash == derive_endpoint_hash(ENDPOINT)
        assert subscription.keys == WEB_KEYS
        assert subscription.platform == PushSubscription.Platform.WEB
        assert subscription.status == PushSubscription.Status.ACTIVE
        assert subscription.last_seen_at is not None
        # The endpoint grants send access — the API must echo only the hash.
        assert "endpoint" not in response.data
        assert response.data["endpoint_hash"] == subscription.endpoint_hash
        assert response.data["created"] is True

    def test_resubscribe_same_endpoint_updates_not_duplicates(self, user_factory):
        user = user_factory()
        client = _client(user)
        first = _subscribe(client)
        second = _subscribe(client, device_label="Renamed device")

        assert first.status_code == 201
        assert second.status_code == 200
        assert PushSubscription.objects.filter(user=user).count() == 1
        subscription = PushSubscription.objects.get(user=user)
        assert subscription.device_label == "Renamed device"

    def test_resubscribe_reactivates_revoked_device(self, user_factory):
        user = user_factory()
        client = _client(user)
        _subscribe(client)
        PushSubscription.objects.filter(user=user).update(status=PushSubscription.Status.REVOKED)

        response = _subscribe(client)
        assert response.status_code == 200
        assert PushSubscription.objects.get(user=user).status == PushSubscription.Status.ACTIVE

    def test_missing_web_keys_rejected(self, user_factory):
        response = _subscribe(_client(user_factory()), keys={})
        assert response.status_code == 400
        assert not PushSubscription.objects.exists()

    def test_missing_endpoint_rejected(self, user_factory):
        response = _subscribe(_client(user_factory()), endpoint="")
        assert response.status_code == 400

    def test_requires_authentication(self):
        response = APIClient().post(
            reverse("notifications:push-subscriptions"),
            {"endpoint": ENDPOINT, "keys": WEB_KEYS},
            format="json",
        )
        assert response.status_code in (401, 403)


class TestUnsubscribe:
    def test_unsubscribe_by_endpoint_revokes(self, user_factory):
        user = user_factory()
        client = _client(user)
        _subscribe(client)

        response = client.delete(reverse("notifications:push-subscriptions"), {"endpoint": ENDPOINT}, format="json")
        assert response.status_code == 204
        assert PushSubscription.objects.get(user=user).status == PushSubscription.Status.REVOKED

    def test_unsubscribe_by_hash_revokes(self, user_factory):
        user = user_factory()
        client = _client(user)
        _subscribe(client)

        response = client.delete(
            reverse("notifications:push-subscriptions"),
            {"endpoint_hash": derive_endpoint_hash(ENDPOINT)},
            format="json",
        )
        assert response.status_code == 204
        assert PushSubscription.objects.get(user=user).status == PushSubscription.Status.REVOKED

    def test_unsubscribe_is_idempotent(self, user_factory):
        client = _client(user_factory())
        _subscribe(client)
        url = reverse("notifications:push-subscriptions")
        assert client.delete(url, {"endpoint": ENDPOINT}, format="json").status_code == 204
        assert client.delete(url, {"endpoint": ENDPOINT}, format="json").status_code == 204

    def test_unsubscribe_unknown_endpoint_is_204(self, user_factory):
        response = _client(user_factory()).delete(
            reverse("notifications:push-subscriptions"), {"endpoint": ENDPOINT}, format="json"
        )
        assert response.status_code == 204

    def test_unsubscribe_without_identifier_rejected(self, user_factory):
        response = _client(user_factory()).delete(reverse("notifications:push-subscriptions"), {}, format="json")
        assert response.status_code == 400

    def test_cannot_revoke_another_users_device(self, user_factory):
        owner, attacker = user_factory(), user_factory()
        _subscribe(_client(owner))

        response = _client(attacker).delete(
            reverse("notifications:push-subscriptions"), {"endpoint": ENDPOINT}, format="json"
        )
        assert response.status_code == 204  # idempotent no-op for the attacker
        assert PushSubscription.objects.get(user=owner).status == PushSubscription.Status.ACTIVE


class TestVapidPublicKey:
    def test_returns_empty_string_until_provisioned(self, user_factory):
        response = _client(user_factory()).get(reverse("notifications:push-vapid-public-key"))
        assert response.status_code == 200
        assert response.data == {"key": ""}

    def test_returns_configured_key(self, user_factory, settings):
        settings.WEBPUSH_VAPID_PUBLIC_KEY = "BConfiguredVapidKey"
        response = _client(user_factory()).get(reverse("notifications:push-vapid-public-key"))
        assert response.data == {"key": "BConfiguredVapidKey"}


class TestDeliveryLedgerConstraint:
    def test_unique_notification_channel_subscription_enforced(self, user_factory):
        user, actor = user_factory(), user_factory()
        notification = Notification.objects.create(
            recipient=user,
            actor=actor,
            verb="test",
            notification_type=Notification.NotificationType.SYSTEM,
        )
        subscription = PushSubscription.objects.create(
            user=user,
            endpoint=ENDPOINT,
            endpoint_hash=derive_endpoint_hash(ENDPOINT),
        )
        NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationDelivery.Channel.WEB_PUSH,
            subscription=subscription,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationDelivery.Channel.WEB_PUSH,
                subscription=subscription,
            )


class TestRegistryQueryCount:
    def test_list_active_for_user_is_constant_queries(self, user_factory):
        """Query-count guard — the fan-out read is one query regardless of
        how many devices a user has registered."""
        from django.db import connection

        user = user_factory()
        repo = OrmPushSubscriptionRepository()
        counter = iter(range(1000))

        def _register(n):
            for _ in range(n):
                endpoint = f"{ENDPOINT}-guard-{next(counter)}"
                PushSubscription.objects.create(
                    user=user,
                    endpoint=endpoint,
                    endpoint_hash=derive_endpoint_hash(endpoint),
                )

        _register(2)
        with CaptureQueriesContext(connection) as few:
            repo.list_active_for_user(user.pk, platform="web")

        _register(5)
        with CaptureQueriesContext(connection) as many:
            result = repo.list_active_for_user(user.pk, platform="web")

        assert len(result) == 7
        assert len(few.captured_queries) == len(many.captured_queries)
