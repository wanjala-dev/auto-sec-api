"""Unit tests for the push endpoint hash derivation (domain value object)."""

from __future__ import annotations

import hashlib

import pytest

from components.notifications.domain.errors import NotificationValidationError
from components.notifications.domain.value_objects.push_endpoint import (
    ENDPOINT_HASH_LENGTH,
    derive_endpoint_hash,
)

pytestmark = pytest.mark.unit

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123:def456"


class TestDeriveEndpointHash:
    def test_is_sha256_hex_of_endpoint(self):
        assert derive_endpoint_hash(ENDPOINT) == hashlib.sha256(ENDPOINT.encode("utf-8")).hexdigest()

    def test_length_and_charset(self):
        digest = derive_endpoint_hash(ENDPOINT)
        assert len(digest) == ENDPOINT_HASH_LENGTH == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_deterministic(self):
        assert derive_endpoint_hash(ENDPOINT) == derive_endpoint_hash(ENDPOINT)

    def test_different_endpoints_differ(self):
        assert derive_endpoint_hash(ENDPOINT) != derive_endpoint_hash(ENDPOINT + "x")

    def test_whitespace_is_stripped_before_hashing(self):
        assert derive_endpoint_hash(f"  {ENDPOINT}\n") == derive_endpoint_hash(ENDPOINT)

    @pytest.mark.parametrize("bad", ["", "   ", None, 42])
    def test_invalid_endpoint_raises(self, bad):
        with pytest.raises(NotificationValidationError):
            derive_endpoint_hash(bad)
