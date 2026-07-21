"""Unit tests for register/revoke push subscription use cases.

One in-memory fake for the registry port (testing skill: one fake per port,
tests enter through the use case). Proves the upsert-idempotency semantics
and input validation without Django or a DB.
"""

from __future__ import annotations

import pytest

from components.notifications.application.ports.push_subscription_registry_port import (
    PushSubscriptionRecord,
    PushSubscriptionRegistryPort,
    UpsertOutcome,
)
from components.notifications.application.use_cases.register_push_subscription_use_case import (
    RegisterPushSubscriptionUseCase,
)
from components.notifications.application.use_cases.revoke_push_subscription_use_case import (
    RevokePushSubscriptionUseCase,
)
from components.notifications.domain.errors import NotificationValidationError
from components.notifications.domain.value_objects.push_endpoint import derive_endpoint_hash

pytestmark = pytest.mark.unit

ENDPOINT = "https://push.example.com/send/token-1"
WEB_KEYS = {"p256dh": "pkey", "auth": "asecret"}


class FakePushSubscriptionRegistry(PushSubscriptionRegistryPort):
    """In-memory fake keyed on endpoint_hash — mirrors the ORM adapter's
    upsert/revoke contract."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def upsert_by_endpoint(
        self,
        *,
        user_id,
        endpoint,
        endpoint_hash,
        keys=None,
        device_label="",
        user_agent="",
        platform="web",
    ) -> UpsertOutcome:
        created = endpoint_hash not in self.rows
        self.rows[endpoint_hash] = {
            "user_id": user_id,
            "endpoint": endpoint,
            "keys": keys or {},
            "device_label": device_label,
            "user_agent": user_agent,
            "platform": platform,
            "status": "active",
        }
        row = self.rows[endpoint_hash]
        return UpsertOutcome(
            record=PushSubscriptionRecord(
                id=endpoint_hash[:8],
                user_id=str(user_id),
                platform=row["platform"],
                endpoint=row["endpoint"],
                endpoint_hash=endpoint_hash,
                keys=row["keys"],
                device_label=row["device_label"],
                status=row["status"],
            ),
            created=created,
        )

    def revoke_by_endpoint_hash(self, *, user_id, endpoint_hash) -> bool:
        row = self.rows.get(endpoint_hash)
        if not row or row["user_id"] != user_id or row["status"] == "revoked":
            return False
        row["status"] = "revoked"
        return True

    def list_active_for_user(self, user_id, *, platform=None):
        return []

    def get_by_id(self, subscription_id):  # pragma: no cover - unused here
        return None

    def mark_expired(self, subscription_id) -> None:  # pragma: no cover - unused here
        pass


@pytest.fixture
def registry():
    return FakePushSubscriptionRegistry()


class TestRegisterPushSubscription:
    def test_first_subscribe_creates(self, registry):
        outcome = RegisterPushSubscriptionUseCase(registry).execute(
            user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS, device_label="MacBook"
        )
        assert outcome.created is True
        assert outcome.record.endpoint_hash == derive_endpoint_hash(ENDPOINT)
        assert outcome.record.status == "active"

    def test_resubscribe_same_endpoint_updates_not_duplicates(self, registry):
        use_case = RegisterPushSubscriptionUseCase(registry)
        first = use_case.execute(user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS)
        second = use_case.execute(user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS, device_label="Renamed")
        assert first.created is True
        assert second.created is False
        assert len(registry.rows) == 1
        assert registry.rows[first.record.endpoint_hash]["device_label"] == "Renamed"

    def test_whitespace_padded_endpoint_hits_same_row(self, registry):
        use_case = RegisterPushSubscriptionUseCase(registry)
        use_case.execute(user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS)
        outcome = use_case.execute(user_id="u1", endpoint=f"  {ENDPOINT} ", keys=WEB_KEYS)
        assert outcome.created is False
        assert len(registry.rows) == 1

    def test_missing_endpoint_rejected(self, registry):
        with pytest.raises(NotificationValidationError):
            RegisterPushSubscriptionUseCase(registry).execute(user_id="u1", endpoint="  ", keys=WEB_KEYS)

    @pytest.mark.parametrize("keys", [{}, {"p256dh": "pkey"}, {"auth": "asecret"}])
    def test_web_platform_requires_crypto_keys(self, registry, keys):
        with pytest.raises(NotificationValidationError):
            RegisterPushSubscriptionUseCase(registry).execute(user_id="u1", endpoint=ENDPOINT, keys=keys)

    def test_unknown_platform_rejected(self, registry):
        with pytest.raises(NotificationValidationError):
            RegisterPushSubscriptionUseCase(registry).execute(
                user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS, platform="windows_phone"
            )


class TestRevokePushSubscription:
    def test_revoke_by_endpoint(self, registry):
        RegisterPushSubscriptionUseCase(registry).execute(user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS)
        revoked = RevokePushSubscriptionUseCase(registry).execute(user_id="u1", endpoint=ENDPOINT)
        assert revoked is True
        assert registry.rows[derive_endpoint_hash(ENDPOINT)]["status"] == "revoked"

    def test_revoke_by_hash(self, registry):
        RegisterPushSubscriptionUseCase(registry).execute(user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS)
        revoked = RevokePushSubscriptionUseCase(registry).execute(
            user_id="u1", endpoint_hash=derive_endpoint_hash(ENDPOINT)
        )
        assert revoked is True

    def test_revoke_is_idempotent(self, registry):
        RegisterPushSubscriptionUseCase(registry).execute(user_id="u1", endpoint=ENDPOINT, keys=WEB_KEYS)
        use_case = RevokePushSubscriptionUseCase(registry)
        assert use_case.execute(user_id="u1", endpoint=ENDPOINT) is True
        assert use_case.execute(user_id="u1", endpoint=ENDPOINT) is False  # no-op, not an error

    def test_revoke_unknown_endpoint_is_noop(self, registry):
        assert RevokePushSubscriptionUseCase(registry).execute(user_id="u1", endpoint=ENDPOINT) is False

    def test_requires_endpoint_or_hash(self, registry):
        with pytest.raises(NotificationValidationError):
            RevokePushSubscriptionUseCase(registry).execute(user_id="u1")

    def test_malformed_hash_rejected(self, registry):
        with pytest.raises(NotificationValidationError):
            RevokePushSubscriptionUseCase(registry).execute(user_id="u1", endpoint_hash="abc123")
