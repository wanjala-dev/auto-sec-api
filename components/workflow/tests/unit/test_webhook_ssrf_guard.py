"""Unit tests for the webhook node's SSRF guard.

Customers supply the webhook URL, so the executor must refuse internal hosts
and the cloud metadata endpoint before issuing a request. Literal-IP URLs are
used so the guard's address checks run without real DNS.
"""

from __future__ import annotations

import pytest

from components.workflow.domain.errors import WorkflowActionError
from components.workflow.infrastructure.adapters.node_actions import (
    _assert_safe_webhook_url,
)

pytestmark = pytest.mark.unit


class TestWebhookSsrfGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/hook",          # loopback
            "http://localhost/hook",           # loopback by name
            "http://169.254.169.254/latest",   # link-local / cloud metadata
            "http://10.0.0.5/hook",            # private (10/8)
            "http://192.168.1.10/hook",        # private (192.168/16)
            "http://172.16.5.4/hook",          # private (172.16/12)
            "http://0.0.0.0/hook",             # unspecified
        ],
    )
    def test_blocks_non_public_addresses(self, url):
        with pytest.raises(WorkflowActionError):
            _assert_safe_webhook_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/x",
            "file:///etc/passwd",
            "gopher://127.0.0.1/x",
            "://nohost",
        ],
    )
    def test_blocks_non_http_schemes(self, url):
        with pytest.raises(WorkflowActionError):
            _assert_safe_webhook_url(url)

    def test_blocks_missing_host(self):
        with pytest.raises(WorkflowActionError):
            _assert_safe_webhook_url("http://")

    @pytest.mark.parametrize(
        "url",
        [
            "http://93.184.216.34/hook",   # public literal IP (example.com range)
            "https://1.1.1.1/hook",        # public literal IP
        ],
    )
    def test_allows_public_addresses(self, url):
        # Should not raise for a public address.
        _assert_safe_webhook_url(url)
