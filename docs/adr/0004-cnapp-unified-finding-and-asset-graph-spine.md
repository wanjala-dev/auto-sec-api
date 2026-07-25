# ADR 0004 — CNAPP unified Finding + Asset-graph spine

**Status:** Accepted · **Date:** 2026-07-25
**Deciders:** Henry + architecture review
**Supersedes/relates:** builds on `docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md` §10 ("The CNAPP lens"),
`docs/plans/PROVENANCE_ACCESS_GRAPH_2026-07-17.md`. Governed by `.claude/rules/architecture-manifesto.md`
and `.claude/skills/architecture/SKILL.md`.

> ADRs 0001–0003 referenced in `.claude/rules/` (explicit-architecture, personas/RBAC, agent-decorator
> framework) are the inherited foundational decisions carried in the rule files + the `agents` skill; this
> is the first ADR authored natively for autosec's `docs/adr/`.

## Context

autosec's end goal is a full **CNAPP** — the convergence of many scanning pillars (CSPM, CWPP/vuln, CIEM,
KSPM, IaC, DSPM) plus the AI-SOC value layer. Today one pillar ships (CSPM via Prowler). An architecture
review (2026-07-25) found the current structure is **scanner-siloed**, the inverse of the CNAPP shape,
which industry references describe as a **unified data model + a single security graph** that many scanners
feed and many lenses read ([Gartner 2025 Market Guide via Orca](https://orca.security/resources/blog/gartner-2025-market-guide-for-cnapp/),
[JupiterOne — CNAPP meets the graph](https://www.jupiterone.com/blog/cnapp-meets-the-graph-why-cloud-native-security-needs-asset-context)).

Concretely, in the code today:

1. **Finding-model fragmentation.** Five disjoint "finding" representations (`CloudPostureFinding` table,
   `project.Task` `ai.*` cards, `agents.DetectorResult`, log `Error/Optimization` structures, provenance
   `ProvenanceEvent`/`AccessGrant`) converge **only** at the `Task` table — a lowest-common-denominator
   denormalization. No shared schema, no shared severity, no lifecycle/dedup.
2. **No canonical asset identity.** `provenance.ProvenanceResource` is access-scoped; `CloudPostureFinding.
   resource_uid` is a bare string; there is **no shared identity** linking them. The vision's crown jewel —
   "wire Prowler findings into the provenance graph = attack paths" — has no shared node to wire to.
3. **Cross-context infrastructure imports.** `agents/infrastructure/.../detectors/cloud_posture.py` imports
   `infrastructure.persistence.cloud_posture.models.CloudPostureFinding`; `.../detectors/provenance.py`
   imports `components.provenance.infrastructure.services.*`. Both break Rule 3 (no cross-context
   infrastructure imports). The current fitness function only checks the `application/` layer, so these
   `infrastructure/`-layer breaks are unenforced.
4. **`Task` is doing two jobs** — it is simultaneously the security *fact* and the remediation *work-item*.
5. **No `ScannerPort`.** Prowler's pipeline is bespoke; adding Trivy/Checkov would copy the whole pipeline.
6. **No finding events.** The `shared_kernel` bus carries only workflow events; scanners → detectors are
   coupled by ORM polling, not events — even though the SOAR trigger catalog already expects `finding_raised`.

Left unaddressed, every new pillar multiplies this debt (a new ORM table + detector + Task adapter each).
The fix must be made **before pillar #2**, and it must stay strictly within Explicit Architecture (DDD +
Hexagonal + Onion + Clean + CQRS, per [Graça](https://herbertograca.com/2017/11/16/explicit-architecture-01-ddd-hexagonal-onion-clean-cqrs-how-i-put-it-all-together/)).

## Decision

Adopt a **hub-and-spoke** structure around a **unified Finding SSOT + a canonical Asset graph**, expressed
entirely in Explicit-Architecture constructs (this is a textbook application of Graça's *"Decoupling the
components"* section — events + shared kernel + read-only cross-component queries + local copies).

```
   SCANNERS (spokes-in)              HUB (the spine)                 CONSUMERS (spokes-out)
 Prowler ─┐  driven adapters   ┌──────────────────────────┐        ┌─ posture_agent (lenses)
 Trivy  ──┤  behind ONE        │ security-graph: Asset node │──────▶ ├─ triage_agent
 Checkov ─┤  ScannerPort  ────▶│  + edges + attack-path     │ events ├─ report (templates)
 KSPM ────┘  → NormalizedFinding│ findings: Finding SSOT     │        ├─ workflow (SOAR)
             (OCSF) via         │  (dedup, lifecycle, risk)  │        └─ notifications / board Task
             FindingObserved    │ shared_kernel: events +    │           (local copy synced via events)
             event              │  value objects + contracts │
                                └────────────┬───────────────┘
                                             │ §6a background job (Celery)
                                             ▼
                               attack-path + contextual-risk materialized tables
                                             ▲ CQRS Query → DTO → HUD
```

Binding rules (see the `architecture` skill for the full set):

- **D1 — One normalized Finding.** A `findings` bounded context owns the Finding SSOT (lifecycle, dedup
  fingerprint, first/last-seen, normalized severity/risk). Every scanner projects into it. `project.Task`
  becomes a **local read-copy + work-item** that references the Finding, synced via events — it is no longer
  the finding.
- **D2 — One canonical Asset identity, by value not FK.** The `security-graph` context (generalized
  `provenance`) owns the `Asset` node. Findings carry a shared **`AssetUrn` value object** (in the shared
  kernel); correlation is a read-only graph query by URN. **No cross-component FK.**
- **D3 — Scanners are driven adapters behind a `ScannerPort`** designed to fit the core's needs (not to
  mimic a tool's CLI). Adding a pillar = a new adapter, never a new pipeline.
- **D4 — Owner-persists via events.** A component never writes data it does not own. Scanning emits
  `FindingObserved` (shared kernel); the `findings` component persists. `findings` emits `FindingRaised`;
  consumers react. Cross-component reads are read-only queries/read-ports or local copies — never a model
  import.
- **D5 — OCSF is the internal lingua franca.** `NormalizedFinding` is OCSF-aligned (emit *and* ingest), so
  scanners normalize once and the platform can interoperate with SIEM/data-lake consumers
  ([OCSF](https://schema.ocsf.io/classes/security_finding)).
- **D6 — Heavy graph aggregations run in the background.** Attack-path + contextual-risk are Celery-
  materialized tables read via CQRS queries — never computed inline (the wanjala architecture skill's §6a
  "heavy aggregations run in the background" HARD RULE + `.claude/rules/performance.md` §7).
- **D7 — Aggregate-light.** Lean frozen-dataclass entities + domain services for cross-entity logic (e.g.
  attack-path correlation is a Domain Service, not an aggregate root). Graça: *"I hardly ever use aggregates."*
- **D8 — Postgres-first.** Adjacency + recursive CTE for the graph; re-evaluate a dedicated graph store only
  if real traversal depth demands it (confirms the vision §10 decision; Neo4j/Cartography stay rejected).

## Consequences

**Positive:** cross-pillar dedup + correlation become graph queries, not `source_type__in=[...]` scans;
attack-path/toxic-combination analysis becomes expressible; a new pillar is an adapter, not a pipeline;
contextual risk ranking (the noise-reduction value) becomes possible because severity is normalized; the
board/agents/report layers decouple from scanners; OCSF gives SIEM interop for free.

**Negative / cost:** a `findings` context and an `Asset` node are net-new; the Prowler write-path and the
board become event-driven (one more hop); a strangler migration is required. This is deliberate: the debt is
modest now and compounds per pillar (the §6a "the optimization IS the architecture" logic).

## Migration (strangler — each step shippable, do before pillar #2)

1. `shared_kernel`: add `Severity` / `RiskBand` / `FindingStatus` / `AssetUrn` value objects +
   `FindingObserved` / `FindingRaised` / `FindingResolved` / `AttackPathDetected` events. Additive.
2. `security-graph`: promote `ProvenanceResource` → canonical `Asset`; backfill from Prowler `resource_uid`
   + provenance; assets keyed by `AssetUrn`.
3. `findings` context: Finding SSOT (dedup + lifecycle); handler persists on `FindingObserved`; emits
   `FindingRaised`. `project.Task` becomes a subscriber holding a local copy. Migrate the CloudPosture
   detector to consume via event/read-port (closes the Rule-3 violation).
4. Extract `ScannerPort` + the shared scan→normalize→emit use case; refit Prowler as the first adapter.
5. Add **Trivy** as a second `ScannerPort` adapter — proves the seam, zero pipeline duplication.
6. Attack-path + contextual-risk **background job** over Findings + Assets + graph → materialized table → HUD.

## Enforcement (fitness functions to add with the phases)

Extend `tests/architecture/` (grounded in modular-monolith fitness-function practice —
[import-linter / pytest-archon](https://dev.to/x4nent/the-modular-monolith-2026-complete-guide-spring-modulith-archunit-fitness-functions-and-lessons-878)):

- Extend `test_cross_context_infrastructure_boundary.py` (or add a sibling) to also forbid **infrastructure-
  layer** cross-context imports of another context's `infrastructure`/`persistence` — the gap that lets the
  detector violations through. Land it with the Phase 3 fix (do not baseline the real violations).
- `test_findings_ownership`: only the `findings` context writes Finding rows.
- `test_no_cross_component_finding_fk`: findings reference assets by `AssetUrn`, not FK.
- `test_board_task_is_a_finding_copy`: `project` must not own finding severity/lifecycle as source of truth.
