"""Read-only IOC-enrichment tool — the triage agent's threat-intel lookup (item #3).

Lets triage ground a verdict in external threat intel instead of the finding's own log
line: given an IP / domain / URL / file-hash, it returns a normalized verdict
(malicious/suspicious/benign/unknown) + score. Reads the integrations context through
its public provider/port (C3). Degrades gracefully (verdict UNKNOWN + reason) when no
provider key is configured — never derails a run.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def enrich_indicator(agent, input_str: str = "") -> str:
    """READ — enrich an IOC against threat intel (VirusTotal today)."""
    raw = (input_str or "").strip()
    provider = None
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            raw = str(data.get("indicator") or data.get("ioc") or data.get("value") or "").strip()
            provider = data.get("provider") or None
        except Exception:
            pass

    from components.integrations.domain.value_objects.indicator import Indicator

    indicator = Indicator.detect(raw)
    if indicator is None:
        return json.dumps(
            {
                "error": "unrecognized_indicator",
                "input": raw[:120],
                "hint": "pass a single IP, domain, URL, or file hash (md5/sha1/sha256).",
            }
        )

    from components.integrations.application.providers.ioc_enrichment_provider import (
        IocEnrichmentProvider,
    )
    from components.integrations.domain.value_objects.enrichment_result import corroborate

    providers = (provider,) if provider else None
    results = IocEnrichmentProvider.enrich_all(indicator, providers=providers)
    agg = corroborate(indicator, results)
    return json.dumps(
        {
            "indicator": indicator.value,
            "kind": indicator.kind.value,
            "verdict": agg.verdict.value,  # most-severe across sources that answered
            "score": agg.score,
            "sources_queried": len(results),
            "sources_answered": len(agg.sources),
            "sources": [
                {
                    "provider": r.provider,
                    "verdict": r.verdict.value,
                    "score": r.score,
                    "positives": r.positives,
                    "detail": r.detail,
                    "error": r.error,
                }
                for r in results
            ],
        }
    )
