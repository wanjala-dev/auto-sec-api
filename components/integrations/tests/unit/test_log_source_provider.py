"""Unit tests for the LogSourceProvider registry (ADR 0008 D4)."""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.providers.log_source_provider import (
    LogSourceProvider,
    UnsupportedLogSourceError,
    get_log_source_provider,
)
from components.integrations.infrastructure.adapters.log_sources.cloudwatch_log_source_adapter import (
    CloudWatchLogSourceAdapter,
)
from components.integrations.infrastructure.adapters.log_sources.s3_log_source_adapter import (
    S3LogSourceAdapter,
)

_MODULE = "components.integrations.application.providers.log_source_provider"


@pytest.mark.unit
class TestLogSourceProvider:
    def test_get_s3_returns_the_s3_adapter(self):
        assert isinstance(LogSourceProvider().get("s3"), S3LogSourceAdapter)

    def test_get_is_case_insensitive(self):
        assert isinstance(LogSourceProvider().get("S3"), S3LogSourceAdapter)

    def test_unknown_kind_raises(self):
        with pytest.raises(UnsupportedLogSourceError):
            LogSourceProvider().get("datadog")  # not registered until its adapter lands

    def test_kinds_lists_registered_sources(self):
        assert "s3" in LogSourceProvider().kinds()

    def test_custom_registry_is_honored(self):
        sentinel = S3LogSourceAdapter()
        provider = LogSourceProvider(sources={"s3": sentinel})
        assert provider.get("s3") is sentinel

    def test_singleton_accessor_is_stable(self):
        assert get_log_source_provider() is get_log_source_provider()

    def test_cloudwatch_registered_when_flag_on(self):
        with mock.patch(f"{_MODULE}._is_cloudwatch_enabled", return_value=True):
            provider = LogSourceProvider()
        assert isinstance(provider.get("cloudwatch"), CloudWatchLogSourceAdapter)
        assert "cloudwatch" in provider.kinds()

    def test_cloudwatch_absent_when_flag_off(self):
        with mock.patch(f"{_MODULE}._is_cloudwatch_enabled", return_value=False):
            provider = LogSourceProvider()
        with pytest.raises(UnsupportedLogSourceError):
            provider.get("cloudwatch")
