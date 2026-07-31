"""Composition root for log sources (ADR 0008 D4).

The only application-layer slot that knows the concrete log-source adapters exist
— maps a source ``kind`` to its ``LogSourcePort`` adapter, exactly like
``PaymentGatewayProvider`` maps a vendor slug to its gateway. The ingest service
resolves sources here and stays SDK-free; nascent adapters (CloudWatch/Datadog/
Splunk) register behind a feature flag as they land.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from components.integrations.application.ports.log_source_port import LogSourcePort

logger = logging.getLogger(__name__)

LogSourceAdapters = dict[str, LogSourcePort]


class UnsupportedLogSourceError(Exception):
    """Raised when no adapter is registered for a source kind."""


class LogSourceProvider:
    """Resolves a ``LogSourcePort`` adapter by source kind (s3, cloudwatch, …)."""

    def __init__(self, sources: Mapping[str, LogSourcePort] | None = None):
        self._sources: LogSourceAdapters = dict(sources or self._default_sources())

    @staticmethod
    def _default_sources() -> LogSourceAdapters:
        from components.integrations.infrastructure.adapters.log_sources.s3_log_source_adapter import (
            S3LogSourceAdapter,
        )

        # S3 is the first (and, in Phase 1, only) real adapter. CloudWatch / Datadog
        # / Splunk register here behind their feature flags as they land (ADR 0008 D5).
        return {S3LogSourceAdapter.KIND: S3LogSourceAdapter()}

    def get(self, kind: str) -> LogSourcePort:
        adapter = self._sources.get((kind or "").lower())
        if adapter is None:
            raise UnsupportedLogSourceError(f"No log-source adapter for kind={kind!r}")
        return adapter

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._sources.keys())


_PROVIDER: LogSourceProvider | None = None


def get_log_source_provider() -> LogSourceProvider:
    """Process-wide singleton (the adapters are stateless)."""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = LogSourceProvider()
    return _PROVIDER
