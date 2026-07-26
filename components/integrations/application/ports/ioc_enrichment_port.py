"""Port: enrich an indicator against a threat-intel source, shaped to the core."""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.integrations.domain.value_objects.enrichment_result import EnrichmentResult
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind


class IocEnrichmentPort(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def supports(self) -> frozenset[IndicatorKind]:
        """The indicator kinds this provider can enrich (e.g. AbuseIPDB = {IP})."""

    @abstractmethod
    def enrich(self, indicator: Indicator) -> EnrichmentResult:
        """Return this provider's normalized read. Never raises — a failure is an
        ``EnrichmentResult.unavailable(...)`` (verdict UNKNOWN + error), so a caller
        can degrade gracefully rather than crash a triage run."""
