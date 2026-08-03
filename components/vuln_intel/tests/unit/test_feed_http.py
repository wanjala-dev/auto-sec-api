"""Unit tests for the bounded HTTP + gunzip feed helpers (supply-chain hardening, W1)."""

from __future__ import annotations

import gzip

import httpx
import pytest

from components.vuln_intel.domain.errors import MalformedFeedError
from components.vuln_intel.infrastructure.adapters.feed_http import download_capped, gunzip_capped

pytestmark = pytest.mark.unit


class TestGunzipCapped:
    def test_roundtrips_within_cap(self):
        raw = gzip.compress(b"cve,epss,percentile\nCVE-1,0.5,0.9\n")
        assert gunzip_capped(raw, max_bytes=1_000_000).startswith(b"cve,epss")

    def test_rejects_bomb_over_cap(self):
        # ~10MB of zeros compresses tiny but inflates past a small cap → must abort.
        raw = gzip.compress(b"\x00" * (10 * 1024 * 1024))
        with pytest.raises(MalformedFeedError):
            gunzip_capped(raw, max_bytes=1024)


class TestDownloadCapped:
    def _client(self, body: bytes) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body)

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_returns_body_within_cap(self):
        with self._client(b"hello") as client:
            assert download_capped("https://x/y", client=client, max_bytes=1_000_000) == b"hello"

    def test_rejects_body_over_cap(self):
        with self._client(b"x" * 5000) as client, pytest.raises(MalformedFeedError):
            download_capped("https://x/y", client=client, max_bytes=1024)
