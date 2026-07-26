"""Composition root + registry for IOC enrichment providers.

Wires provider names to adapters (the policy the plan §2 keeps in the application
layer). Adding a provider (AbuseIPDB, GreyNoise, OTX) is one entry here + one adapter —
callers keep talking to ``IocEnrichmentPort``.
"""

from __future__ import annotations

from components.integrations.application.ports.ioc_enrichment_port import IocEnrichmentPort
from components.integrations.domain.value_objects.enrichment_result import EnrichmentResult
from components.integrations.domain.value_objects.indicator import Indicator

# provider name / alias -> builder. Lazy imports keep infra out of import-time.
_BUILDERS: dict[str, str] = {
    "virustotal": "virustotal",
    "vt": "virustotal",
}

# Order tried by ``enrich`` when no provider is named (extend as adapters land).
_DEFAULT_ORDER = ("virustotal",)


class IocEnrichmentProvider:
    @staticmethod
    def build_adapter(provider_name: str) -> IocEnrichmentPort | None:
        canonical = _BUILDERS.get((provider_name or "").strip().lower())
        if canonical == "virustotal":
            from components.integrations.infrastructure.adapters.ioc.virustotal_adapter import (
                VirusTotalAdapter,
            )

            return VirusTotalAdapter()
        return None

    @staticmethod
    def available_providers() -> tuple[str, ...]:
        return _DEFAULT_ORDER

    @staticmethod
    def enrich(indicator: Indicator, *, provider: str | None = None) -> EnrichmentResult:
        """Enrich against a named provider, or the first default that supports the kind.

        Always returns a result (never raises); if nothing can serve it, an
        ``EnrichmentResult.unavailable`` with ``no_provider``."""
        names = (provider,) if provider else _DEFAULT_ORDER
        last: EnrichmentResult | None = None
        for name in names:
            adapter = IocEnrichmentProvider.build_adapter(name)
            if adapter is None or indicator.kind not in adapter.supports:
                continue
            result = adapter.enrich(indicator)
            last = result
            if result.error is None:  # a real answer (incl. BENIGN/UNKNOWN-not-found)
                return result
        return last or EnrichmentResult.unavailable("none", indicator, "no_provider")
