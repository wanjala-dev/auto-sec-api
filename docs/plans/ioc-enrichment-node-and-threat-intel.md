# Plan — IOC-enrichment workflow node + threat-intel connector set

> **Status:** proposed (roadmap item #3 from `docs/competitive/torq-vs-autosec-soc.md`).
> **Motivation:** the single biggest *workflow-content* gap vs Torq's phishing/IOC playbook
> is that autosec has **no enrichment node and no threat-intel connectors** — so a security
> playbook can branch and notify but cannot *learn anything new about an indicator*. The same
> missing primitive is what keeps the deep-agent arm's "root-cause context" pinned to a single
> error line's own evidence (no external corroboration). Closing it lifts *both* the workflow
> builder and the agent's grounding at once.
>
> **Non-goal:** chasing Torq's 300+ integration count. This is a **small, deep** catalog
> (4 providers) behind one clean seam, reusable by both the workflow engine and the agent.

## 1. What we're adding

1. A new workflow node type **`enrich`** in `components/workflow/` — given an indicator (IP,
   domain, URL, or file hash) from the run context, call a threat-intel provider through a
   **port**, and write a normalized verdict onto the step output so downstream
   `condition`/`switch` nodes can branch on it.
2. A threat-intel **enrichment port** + **provider registry** in `components/integrations/`,
   with four adapters: **VirusTotal**, **AbuseIPDB**, **GreyNoise**, **AlienVault OTX**.
3. Reuse the same port from the deep-agent arm as a **risk-tier-0 (read-only) tool** so
   triage specialists can enrich an indicator during investigation.

This deliberately lands on the **existing node/detector/registry seam** (extend, don't fork),
per `.claude/rules/dry-reuse.md` and `no-shortcuts.md`.

## 2. Architecture (Explicit Architecture placement)

```
components/integrations/
  application/ports/
    ioc_enrichment_port.py         # IocEnrichmentPort (ABC): enrich(indicator) -> EnrichmentResult
  application/providers/
    ioc_enrichment_provider.py     # registry: name -> adapter; composition root (policy)
  domain/
    value_objects/
      indicator.py                 # Indicator(kind: IndicatorKind, value: str) — frozen, validated
      enrichment_result.py         # EnrichmentResult(provider, indicator, verdict, score, raw, ...)
  infrastructure/adapters/ioc/
    virustotal_adapter.py          # implements IocEnrichmentPort
    abuseipdb_adapter.py
    greynoise_adapter.py
    otx_adapter.py

components/workflow/
  domain/constants.py              # NODE_TYPES += "enrich"; NODE_CONFIG_SCHEMA for it
  domain/validators.py             # validate enrich-node config at publish time
  infrastructure/adapters/node_actions.py
                                   # _execute_enrich(run, node, context) -> step output
```

- **Port lives in the application layer** (`application/ports/`), not the context root
  (architecture-manifesto Rule 1).
- **Provider/registry lives in `application/providers/`** — it decides which adapter serves a
  provider name; that wiring is a policy decision (Rule 9).
- **Adapters implement the port** and are the *only* place the vendor SDK/HTTP client is
  imported (Rule 5 / Rule 10). No `import requests`-to-VirusTotal in `node_actions.py`.
- **Domain value objects are frozen dataclasses** with `__post_init__` validation
  (`Indicator` rejects a malformed IP/hash; `IndicatorKind` is an enum).

## 3. Domain value objects

```python
# components/integrations/domain/value_objects/indicator.py
class IndicatorKind(str, Enum):
    IP = "ip"; DOMAIN = "domain"; URL = "url"; FILE_HASH = "file_hash"

@dataclass(frozen=True)
class Indicator:
    kind: IndicatorKind
    value: str
    def __post_init__(self):
        if not self.value.strip():
            raise ValueError("indicator value cannot be empty")
        # kind-specific shape checks (IPv4/6, sha256/md5, host, url scheme)

# components/integrations/domain/value_objects/enrichment_result.py
class EnrichmentVerdict(str, Enum):
    MALICIOUS = "malicious"; SUSPICIOUS = "suspicious"; BENIGN = "benign"; UNKNOWN = "unknown"

@dataclass(frozen=True)
class EnrichmentResult:
    provider: str
    indicator: Indicator
    verdict: EnrichmentVerdict
    score: int              # normalized 0-100 across providers
    positives: int | None   # e.g. VT malicious engine count
    raw: dict               # provider payload (for the run timeline / audit)
    error: str | None = None
```

Normalization matters: VirusTotal returns engine counts, AbuseIPDB a 0-100 confidence,
GreyNoise a classification, OTX pulse counts. Each adapter maps its native shape onto the
shared `(verdict, score)` so a downstream `condition` node can branch on
`steps.<node>.verdict == "malicious"` regardless of provider — the same normalization
discipline the Finding SSOT applies to findings.

## 4. Port

```python
# components/integrations/application/ports/ioc_enrichment_port.py
class IocEnrichmentPort(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def supports(self) -> frozenset[IndicatorKind]: ...   # e.g. AbuseIPDB = {IP}

    @abstractmethod
    def enrich(self, indicator: Indicator) -> EnrichmentResult: ...
```

## 5. The `enrich` node

Node config (validated at publish time):

```json
{
  "type": "enrich",
  "config": {
    "provider": "virustotal",
    "indicator_kind": "url",
    "indicator_path": "$.trigger.url",   // dotted path into the run context
    "cache_ttl_seconds": 21600           // 6h, mirrors Torq's IOC cache pattern
  }
}
```

`_execute_enrich`:
1. Resolve the indicator from `context` via `indicator_path` (reuse the existing dotted-path
   resolver that `condition`/`switch` already use — do **not** write a second resolver).
2. Build an `Indicator`; if the kind isn't supported by the provider, fail the node with a
   clear message (surfaced in the run timeline).
3. **Cache-first** (Django Redis cache, key `ioc:{provider}:{kind}:{value}`, TTL from config)
   — this is Torq's cache-backed enrichment pattern and it protects our per-key API quotas.
4. On miss, call `provider.enrich(indicator)`; store the `EnrichmentResult`.
5. Write the normalized result to the step output so
   `steps.<node_id>.{verdict,score,positives}` is branchable.

**Reliability / rules compliance:**
- Enrichment is a **network call >100ms** → it runs inside the existing Celery workflow
  walker, never in a request path (performance.md §7). No new synchronous HTTP in a controller.
- API keys come from the existing **secret envelope** (`components/integrations/.../secret_envelope.py`),
  never from settings literals or logs (logging.md §4). Adapters log `provider` + `indicator
  kind` + verdict, **never** the API key and never the full raw payload at INFO.
- Errors: an adapter raises on transient provider errors (let the node's retry handle it);
  a definitive "not found" returns `verdict=UNKNOWN` rather than raising (logging.md §7 — only
  swallow what you understand).

## 6. Reuse from the deep-agent arm (no second implementation)

Expose the **same port** as a triage tool:

```
components/agents/infrastructure/adapters/langchain/tools/enrich_indicator_tool.py
  -> calls get_ioc_enrichment_provider().get(provider).enrich(indicator)
  -> tagged risk-tier 0 (read-only) in components/agents/application/policies/tool_risk.py
```

This is the payoff: the specialist that today grounds a suggestion against one error line can
now enrich an IP/hash/domain pulled from that log and corroborate externally — closing the
"one-error-message grounding" limit called out in the teardown (§3/§5). No new enrichment code
in the agent; it consumes the integrations port.

## 7. Build order (each independently shippable, tested)

1. Domain VOs (`Indicator`, `EnrichmentResult`) + unit tests (pure logic, no DB/network).
2. Port + provider registry + **one** adapter (VirusTotal) behind a mocked HTTP client;
   contract test with a recorded fixture (no live calls in CI).
3. `enrich` node type + `_execute_enrich` + publish-time validator + an **integration test**
   that drives a run through `trigger → enrich → condition(malicious) → notify`, with the
   provider mocked. (This also exercises roadmap item #1's fixed dispatch/target path once
   that lands — sequence item #1 first.)
4. Remaining adapters (AbuseIPDB, GreyNoise, OTX) — each = one adapter + one contract test.
5. Deep-agent `enrich_indicator` tool (risk-tier 0) + a triage-flow test.

## 8. Dependencies / sequencing

- **Blocked by roadmap item #1** for the *workflow* path to be demonstrable end-to-end (a
  finding must actually start a run before an `enrich` node can run in a security playbook).
  The node + adapters can be built and unit/integration-tested in parallel with item #1 using
  a contact-target run; the finding-target E2E test lands after #1.
- **Enables** a real phishing/IOC playbook template (our first genuinely useful seeded
  security workflow) and richer agent grounding.
- **Feeds** roadmap item #4 (connector registry): the enrichment provider registry is the
  first concrete instance of the generic connector-registry abstraction — build it here in a
  way #4 can generalize, don't pre-abstract.

## 9. Out of scope (explicitly)

- Sandbox detonation providers (Joe Sandbox / Hybrid Analysis) — add later behind the same port.
- A visual node-config UI — the workflow UI is feature-flagged off (roadmap item #8); this
  plan delivers the engine primitive and API/config, not the builder affordance.
- Rate-limit orchestration beyond per-key caching — revisit if we hit provider quotas.
