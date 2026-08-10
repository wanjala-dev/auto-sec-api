"""Composition root for agent-runtime telemetry (ADR 0023 D1/D2).

The one application-layer slot that knows which concrete ``AgentTelemetryPort``
adapters exist — the ``LogSourceProvider`` pattern, sixth use of the registry
template. A new capture mechanism is a class + one line here.

The whole capability is dark behind :data:`FEATURE_FLAG`, a **sibling** of
``feature.provenance_graph`` rather than a reuse of it (ADR 0021 D6: a workspace
opted into one observation surface has not consented to another). It fails
CLOSED — a missing flag or a flag-service outage means off.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from components.provenance.application.ports.agent_telemetry_port import AgentTelemetryPort
from components.provenance.application.use_cases.ingest_agent_telemetry_use_case import (
    IngestAgentTelemetryUseCase,
)
from components.provenance.domain.errors import UnsupportedAgentTelemetryKindError

logger = logging.getLogger(__name__)

#: Its own flag. Dark by default; seeded in ``seed_feature_flags`` and listed in
#: ``PROD_DISABLED_FLAGS``.
FEATURE_FLAG = "feature.agent_runtime_accountability"

AgentTelemetryAdapters = dict[str, AgentTelemetryPort]


class AgentTelemetryProvider:
    """Resolves an ``AgentTelemetryPort`` adapter by source kind."""

    def __init__(self, adapters: Mapping[str, AgentTelemetryPort] | None = None):
        self._adapters: AgentTelemetryAdapters = dict(adapters or self._default_adapters())

    @staticmethod
    def _default_adapters() -> AgentTelemetryAdapters:
        from components.provenance.infrastructure.adapters.agent_telemetry.otlp_json_agent_telemetry_adapter import (
            OtlpJsonAgentTelemetryAdapter,
        )

        # OTLP/HTTP JSON is the lowest-common-denominator capture shape: it works
        # on any Vercel plan and any AI SDK version, a customer script can POST it
        # today, and a Vercel Trace Drain emits exactly this — so the drain lands
        # later as configuration, not as a second ingest path.
        return {OtlpJsonAgentTelemetryAdapter.KIND: OtlpJsonAgentTelemetryAdapter()}

    def get(self, kind: str) -> AgentTelemetryPort:
        adapter = self._adapters.get((kind or "").lower())
        if adapter is None:
            raise UnsupportedAgentTelemetryKindError(f"No agent-telemetry adapter for kind={kind!r}")
        return adapter

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._adapters.keys())


_PROVIDER: AgentTelemetryProvider | None = None


def get_agent_telemetry_provider() -> AgentTelemetryProvider:
    """Process-wide singleton (the adapters are stateless)."""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = AgentTelemetryProvider()
    return _PROVIDER


def get_ingest_agent_telemetry_use_case() -> IngestAgentTelemetryUseCase:
    from components.provenance.infrastructure.repositories.agent_activity_ledger_repository import (
        AgentActivityLedgerRepository,
    )

    return IngestAgentTelemetryUseCase(
        ledger=AgentActivityLedgerRepository(),
        adapters=get_agent_telemetry_provider(),
    )
