---
name: architecture
upstream: none
why: |
  Deliberately independent of wanjala-nonprofit/architecture, which shares this name but
  documents the wanjala NONPROFIT platform (grants, sponsorship, donations). This skill is
  autosec's own CNAPP hub-and-spoke target. Same name, no lineage — nothing to sync.
  See .claude/rules/skills-and-plugins.md.
description: |
  Invoke BEFORE any structural or layer-crossing change in the auto-sec (autosec) backend: adding or
  splitting a bounded context, adding a security scanning pillar (a new scanner/engine), touching the
  finding or asset data model, wiring one context to another, adding a domain/application event, or moving
  code between layers. autosec follows Explicit Architecture (DDD + Hexagonal + Onion + Clean + CQRS, per
  Herberto Graça) and is evolving into a full CNAPP. This skill is the durable playbook that keeps that
  evolution from re-fragmenting: it loads the layer rules, the CNAPP hub-and-spoke target (a unified Finding
  SSOT + a canonical Asset graph that many scanners feed and many lenses read), the component-decoupling
  rules that matter once there is more than one pillar, the KNOWN architecture debt with its fix + phase,
  and the fitness-function enforcement. Unique to this repo — do not copy the wanjala nonprofit architecture
  specifics. Authoritative companions: `.claude/rules/architecture-manifesto.md`,
  `.claude/rules/bounded-context-structure.md`, `docs/adr/0004-cnapp-unified-finding-and-asset-graph-spine.md`.
---

# Auto-Sec Architecture — Explicit Architecture, built to converge into a CNAPP

**Read this before structural work.** It exists because a 2026-07-25 review found the finding/asset model
was **scanner-siloed** — fine for one pillar (CSPM/Prowler), but the *inverse* of the CNAPP shape and set to
multiply debt with every pillar. This skill encodes the target and the rules so we fix it once and never
re-fragment.

The authoritative rule files are `.claude/rules/architecture-manifesto.md` (the 10 Explicit-Architecture
rules), `.claude/rules/bounded-context-structure.md` (the canonical directory tree), and
`.claude/rules/persistence-and-orm.md`. This skill does not restate them — it adds the **CNAPP-scaling
architecture** and the **security-domain decisions** those files predate.

> This is autosec's OWN skill. The `wanjala:architecture` plugin skill describes the *source* nonprofit
> platform (sponsorship/budgeting, 4-DB tenant router). Take its Explicit-Architecture **principles**; ignore
> its domain specifics. autosec is **single-DB** and its domain is security.

---

## 1. Mental model

autosec is a **modular monolith of security bounded contexts** built on Explicit Architecture
([Graça, 2017](https://herbertograca.com/2017/11/16/explicit-architecture-01-ddd-hexagonal-onion-clean-cqrs-how-i-put-it-all-together/)):

- **Three blocks:** delivery (UI/API/CLI/workers) → **application core** (the app) → infrastructure (tools).
  Tools (Postgres, Prowler, Trivy, S3, LangChain, Stripe) live *outside*; adapters connect them.
- **Ports live inside the core** (`application/ports/`), designed **to fit the core's needs, not to mimic a
  tool's API**. Adapters (infrastructure) implement them. Dependencies point **inward** (Onion).
- **Driving adapters** (`api/controller.py`, `cli/`, `workers/tasks.py`) tell the core what to do.
  **Driven adapters** (`infrastructure/adapters|repositories|gateways/`) are told by the core what to do — a
  scanner engine (Prowler/Trivy) is a **driven adapter**, told by us to scan.
- **Components = bounded contexts** (`components/<ctx>/`), packaged by domain (screaming architecture), each
  owning its data. A component has **no reference to another component's code — not even its interfaces.**
  Cross-component wiring is by **events (shared kernel)**, **read-only queries/ports**, or **local copies
  synced by events** — never a direct model/infrastructure import.
- **Aggregate-light.** Entities are lean frozen dataclasses with invariants in `__post_init__`; cross-entity
  logic is a **Domain Service**. Graça: *"I hardly ever use aggregates."* Don't impose aggregate-root
  ceremony.
- **CQRS.** Writes go through use cases/command handlers; reads are Query objects → DTOs. Heavy aggregations
  are **materialized in the background** and the query just reads the row (see §6).

If you're adding a scanner, a finding type, an asset concept, or a cross-context call — the rest of this
skill is the law. When unsure where code goes, use the decision trees in §4.

---

## 2. The CNAPP shape: hub-and-spoke, not scanner-silo (the core thesis)

A full CNAPP is a **unified data model + a single security graph** that connects misconfigurations →
vulnerabilities → identities → exposure, so the ~1% of findings that form real attack paths can be ranked
and the rest of the noise dropped (Gartner 2025 Market Guide;
[Orca unified data model](https://orca.security/resources/blog/unified-security-platform/),
[JupiterOne — CNAPP meets the graph](https://www.jupiterone.com/blog/cnapp-meets-the-graph-why-cloud-native-security-needs-asset-context)).
autosec's differentiator is the **AI-SOC value layer on top** (grounded triage, validation, governance,
report) — never out-scanning Wiz/Orca. See `docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md` §10.

**Target structure (see `docs/adr/0004`):**

```
   SCANNERS (spokes-in)              HUB (the spine)                 CONSUMERS (spokes-out)
 Prowler ─┐  driven adapters   ┌──────────────────────────┐        ┌─ posture / triage / cloud_posture agents
 Trivy  ──┤  behind ONE        │ security-graph: Asset node │──────▶ ├─ report (templates)
 Checkov ─┤  ScannerPort  ────▶│  + edges + attack-path     │ events ├─ workflow (SOAR)
 KSPM ────┘  → NormalizedFinding│ findings: Finding SSOT     │        └─ notifications / board Task
             (OCSF) via         │  (dedup, lifecycle, risk)  │           (LOCAL COPY synced via events)
             FindingObserved    │ shared_kernel: events +    │
             event              │  value objects + contracts │
                                └────────────┬───────────────┘
                                             │ §6 background job (Celery, Postgres CTE)
                                             ▼   materialized attack-path + risk tables → CQRS → HUD
```

The **hub** is: one **`findings`** context (the Finding SSOT), one **security-graph** context (generalized
`provenance`, owning the `Asset` node + edges), and a **minimal shared kernel** (contracts only). Scanners
are spokes-in; agents/report/workflow/board are spokes-out. **This is the shape all new work must move
toward.** Do not add a scanner as a new silo.

---

## 3. Component-decoupling rules (the part that matters at N pillars)

This is Graça's *"Decoupling the components"* section, made concrete. **These are the rules the current code
breaks; they are the reason for this skill.**

- **C1 — Events live in the shared kernel, never in the originating context.** A cross-context event
  (`FindingRaised`, `AttackPathDetected`) goes in `components/shared_kernel/domain/events.py` so both emitter
  and subscriber depend on the kernel, not on each other. (See `TaskAcceptedFromBoard` for the established
  pattern.) An event used only *inside* one context may live in that context's `domain/events/`.
- **C2 — A component never changes data it does not own.** Scanning does **not** write `Finding` rows.
  Scanning emits `FindingObserved`; the `findings` context (the owner) persists. `findings` emits
  `FindingRaised`; consumers react. This is "triggering logic in other components" — owner-persists.
- **C3 — Getting another component's data is read-only.** Use a **read-port / Query object** (see
  `report/application/ports/finding_source_port.py` + `.../board_finding_repository.py` for the sanctioned
  pattern) **or a local copy synced via events**. **Never import another context's models or infrastructure.**
- **C4 — Correlate by a shared value-object identity, not a cross-component FK.** Findings carry an
  `AssetUrn` (shared kernel); the graph owns the `Asset`. Attack-path is a read-only query by URN. A hard FK
  from `Finding.asset_id` into another context's table is coupling — forbidden.
- **C5 — Ports fit the core, not the tool.** `ScannerPort.scan(account, creds) -> list[NormalizedFinding]`
  expresses what the core wants; the Prowler adapter maps Prowler's OCSF output into it. Never let the port
  mirror a scanner's CLI/flags.
- **C6 — One normalized Finding, OCSF-aligned.** All scanners project into `NormalizedFinding` (shared
  severity/status/risk value objects). Do **not** add a per-pillar finding table. OCSF is the internal lingua
  franca — emit *and* ingest it ([schema.ocsf.io](https://schema.ocsf.io/classes/security_finding)).
- **C7 — The board `Task` is a local copy + work-item, not the finding.** It references a Finding and is
  synced via `FindingRaised`/`FindingResolved` — Graça's "segregated storage: local copy updated via domain
  events." Severity/lifecycle source-of-truth is the `findings` context.

---

## 4. Where does it go? (decision trees)

Canonical layout is `.claude/rules/bounded-context-structure.md`. CNAPP-specific placement:

**"I'm adding a new scanner / engine (Trivy, Checkov, a CVE feed)."**
→ A **driven adapter** implementing `ScannerPort`, in the scanning context's `infrastructure/adapters/`.
It normalizes the tool's output to `NormalizedFinding` and the shared scan use case emits `FindingObserved`.
**Not** a new pipeline, **not** a new finding table, **not** a new detector reading a new table.

**"A scan produced a finding."**
→ It becomes a `NormalizedFinding` → `FindingObserved` event → the **`findings`** context persists it
(dedup on fingerprint, lifecycle). Only `findings` writes findings.

**"I need asset / resource / relationship / attack-path logic."**
→ The **security-graph** context (generalized `provenance`). Assets keyed by `AssetUrn`. Attack-path is a
**Domain Service** + a §6 materialized table. Postgres CTE — no graph DB (ADR 0004 D8).

**"Context A needs data from context B."**
→ Read-only: a read-port/Query in A, or a local copy in A synced by B's events (C3). Never import B's models.

**"Two contexts must react to the same thing."**
→ A shared-kernel event (C1). Emitter and subscribers never import each other.

**"Should this be a new bounded context?"**
→ Only if it has its own ubiquitous language + lifecycle + clear ownership (`.claude/rules` §"bounded
context"). `findings` and the security-graph earn it. A pillar's *scanning mechanism* usually does **not** —
it's an adapter + normalization, converging on the shared Finding. Start as a module; extract later.

**"It's a heavy aggregation (posture score, risk, attack-path, KPI rollup)."** → §6 (background, always).

---

## 5. The normalized Finding + OCSF

Adopt **OCSF** (Open Cybersecurity Schema Framework — the vendor-neutral standard backed by AWS/Splunk/CrowdStrike/PANW)
as the internal finding schema. autosec already ingests Prowler's OCSF; lean into it as the lingua franca so
that (a) every scanner normalizes once, (b) severity/confidence/risk are comparable across pillars, and (c)
autosec can emit OCSF to a customer's SIEM/data-lake without a translation layer
([OCSF security_finding](https://schema.ocsf.io/classes/security_finding),
[OCSF overview](https://ocsf.io/)). Shared-kernel value objects: `Severity`, `RiskBand`, `FindingStatus`,
`AssetUrn`. `NormalizedFinding` carries `asset_urn`, `pillar`/`class`, `severity`, `confidence`, `remediation`,
`compliance`, a stable `fingerprint` (for dedup), and `first_seen`/`last_seen`.

---

## 6. Heavy graph/aggregation work runs in the background (HARD RULE)

Inherited from the wanjala architecture skill's §6a "heavy aggregations run in the background" HARD RULE and
autosec's `.claude/rules/performance.md` §7 (Celery for anything >100ms) — non-negotiable here: **any
computation that scans many rows or walks the graph — attack-path traversal, contextual-risk scoring, posture/KPI rollups, findings-by-framework — MUST
run as a Celery task writing a precomputed table; the API/HUD read is a single indexed `SELECT`.** Attack-path
and risk are the canonical case: a nightly (or event-triggered) job materializes `attack_path` / `asset_risk`
rows via recursive CTE over Findings + Assets + graph edges; the query side is a thin CQRS read. Never compute
these inline in a request. "The optimization IS the architecture; retrofitting after ship is a P1."

---

## 7. The migration this skill was written to drive — DONE (verified 2026-08-12)

This section used to list six live architecture debts and tell you not to add a pillar until they landed.
**All six are resolved, and the enforcement gap that hid one of them is closed.** Verified against the code,
not against the plan:

| # | The old debt | Where it lives now |
|---|---|---|
| 1 | Finding fragmentation — 5 reps converging only at `project.Task` | **`components/findings` is the SSOT** (`infrastructure/persistence/findings/models.py`), the sole writer |
| 2 | No canonical asset | `AssetUrn` in `shared_kernel/domain/security.py`; findings correlate by URN, not FK (C4) |
| 3 | Cross-context infra imports in `agents/.../detectors/` | Gone — grep is clean |
| 4 | `Task` is the finding | `handle_finding_raised_board` builds the card **from `FindingRaised`**; `Task` is a local copy (C7) |
| 5 | No `ScannerPort` | `shared_kernel/application/ports/scanner_port.py` |
| 6 | No finding events | `FindingObserved` / `FindingRaised` / `FindingResolved` in `shared_kernel/domain/events.py` |

**The enforcement gap is closed too.** `test_cross_context_infrastructure_boundary.py` no longer checks only
the application layer: `test_non_application_layers_...` covers **every other layer** — infrastructure
included — with **zero allowlist**. That is the fitness function §9 asked for, and it is why debt #3 cannot
silently return.

### What the live pipeline actually does now

```
Scanner (driven adapter, ephemeral k8s Job)
  → FindingObserved                       (shared kernel)
  → components/findings                   ← SSOT: dedup on fingerprint, lifecycle, risk
  → FindingRaised
      ├─→ agents/finding_raised_board_handler   → board Task (local copy)
      ├─→ findings/finding_risk_recompute       → contextual-risk rescoring
      └─→ notifications/finding_raised_alert    → Slack / alerts
```

All deterministic. **No LLM anywhere in ingest** — the deep agent and `RubricMiddleware` enter only at
TRIAGE, once a finding exists, and only for the agents in `CRITIC_ENABLED_AGENTS`. Grading ingest would be
meaningless: it is schema mapping, not judgment. Do not "improve" this by routing ingest through an agent.

`_SOURCE_BOARD` in the board handler maps each scanner source onto its card builder. All four mapped sources
(`cloud_posture.prowler`, `cloud_graph.attack_path`, `container_security.trivy`, `code_security.opengrep`)
carry `flag: None` — **graduated**, no dual-write, no cutover flag left to flip. A source absent from that
map is simply not board-surfaced via the SSOT path; check before assuming it is.

### What this means for you

The old instruction — *"do not add a pillar until Phases 1–4 land"* — **no longer applies**. The spine
exists. Adding a pillar is now the thing it was built for: a `ScannerPort` driven adapter that normalizes to
`NormalizedFinding` and emits `FindingObserved`. §2, §3 and §4 are the live contract; §7 is now history.

**If you find a NEW violation, add it here with a date and a file reference** — do not let this section drift
back into describing solved problems, which is exactly what it had done by 2026-08-12.

---

## 8. Anti-patterns (autosec / CNAPP-specific)

| Anti-pattern | Do instead |
|---|---|
| New pillar → new `XyzFinding` ORM table + new detector reading it | One `NormalizedFinding` + `FindingObserved`; scanner is a `ScannerPort` adapter (C6, §4) |
| A detector/adapter in `agents` importing another context's models or `infrastructure.services` | Consume `FindingRaised` or a read-port (C3); never import another context's infra |
| `Finding.asset_id` FK into the graph context's table | Carry `AssetUrn` value object; correlate by read-only query (C4) |
| Scanning writes `Finding` rows directly | Emit `FindingObserved`; the `findings` owner persists (C2) |
| Board `Task` owning severity/lifecycle as source of truth | `Task` is a local copy of a Finding (C7) |
| `ScannerPort` shaped like Prowler's CLI | Shape it to the core's need: `scan()->list[NormalizedFinding]` (C5) |
| Posture score / attack-path / risk computed inline in a view | Background-materialize; view reads the row (§6) |
| Adding a graph DB (Neo4j/Cartography) for the asset graph | Postgres adjacency + recursive CTE (ADR 0004 D8) |
| Heavy aggregate-root loading whole object graphs | Lean entities + Domain Services (aggregate-light) |
| Cross-context comms via a new context-owned event | Event in the shared kernel (C1) |

---

## 9. Enforcement — fitness functions

autosec already enforces boundaries with `tests/architecture/` (import-graph fitness functions in the
modular-monolith tradition — see
[the 2026 modular-monolith guide](https://dev.to/x4nent/the-modular-monolith-2026-complete-guide-spring-modulith-archunit-fitness-functions-and-lessons-878);
Python's practical stack is pytest-archon / import-linter + ruff, checked at test-time). Existing tests
include `test_cross_context_import_rules.py`, `test_cross_context_infrastructure_boundary.py` (app-layer
only), `test_application_layer_purity.py`, `test_controller_orm_import_rules.py`,
`test_hexagonal_boundary_rules.py`, `test_repository_entity_ownership_rules.py`.

**Add with the migration (each lands beside the code it guards — never baseline a real violation):**

- Extend the infra-boundary test to forbid a context's `infrastructure/` importing **another** context's
  `infrastructure`/`persistence` (closes debt #3). Use the established `_TRANSITIONAL_ALLOWLIST` pattern
  *only* for genuinely-staged items, each with a tracking comment + ADR reference.
- `test_findings_is_sole_finding_writer` — only `components/findings` writes Finding rows.
- `test_findings_reference_assets_by_urn` — no FK from findings into the graph context.
- `test_board_task_is_not_finding_ssot` — `project` does not own finding severity/lifecycle.
- `test_scanner_adapters_implement_scanner_port` — every scanner engine is a `ScannerPort` driven adapter.

Keep the suite green: fix the fixture or the code, never weaken a real assertion.

---

## 10. Migration roadmap — COMPLETE (verified 2026-08-12)

The ADR-0004 strangler is done. Kept as a record of what shipped, because the shape it produced is the
contract every new pillar plugs into:

1. ✅ shared_kernel value objects + finding events (`FindingObserved` / `FindingRaised` / `FindingResolved`).
2. ✅ `Asset` keyed by `AssetUrn`; findings correlate by URN, never by cross-context FK.
3. ✅ `findings` context (SSOT + dedup + lifecycle); `Task` demoted to a local copy built from `FindingRaised`;
   detectors off the ORM import.
4. ✅ `ScannerPort` + shared scan use case; Prowler the first adapter.
5. ✅ Trivy as the second adapter — the seam is proven, not theoretical.
6. ✅ Attack-path + contextual-risk background job → materialized table → HUD (ADR 0013).

Four pillars now ride the spine: `cloud_posture.prowler`, `container_security.trivy`,
`cloud_graph.attack_path`, `code_security.opengrep`. **"Unify before you multiply" is satisfied — multiply
freely, along the seam.** A fifth pillar is a `ScannerPort` adapter plus one `_SOURCE_BOARD` entry, and it
should require no change to the spine. If it does, that is the signal the spine is wrong, not the pillar.

---

## 11. References

- **Explicit Architecture** — [Graça, "DDD, Hexagonal, Onion, Clean, CQRS… how I put it all together"](https://herbertograca.com/2017/11/16/explicit-architecture-01-ddd-hexagonal-onion-clean-cqrs-how-i-put-it-all-together/) (the model this whole repo follows).
- **Authoritative rules** — `.claude/rules/architecture-manifesto.md`, `.claude/rules/bounded-context-structure.md`, `.claude/rules/persistence-and-orm.md`, `.claude/rules/performance.md` (§7 Celery for >100ms; the "background-materialized aggregation table" HARD RULE is imported from the wanjala architecture skill §6a), `.claude/rules/dry-reuse.md`, `.claude/rules/no-shortcuts.md`.
- **Decision** — `docs/adr/0004-cnapp-unified-finding-and-asset-graph-spine.md`.
- **Product direction** — `docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md` (§10 CNAPP lens), `docs/plans/PROVENANCE_ACCESS_GRAPH_2026-07-17.md`.
- **CNAPP / graph** — [Gartner 2025 Market Guide takeaways (Orca)](https://orca.security/resources/blog/gartner-2025-market-guide-for-cnapp/), [Orca unified data model](https://orca.security/resources/blog/unified-security-platform/), [JupiterOne — CNAPP meets the graph](https://www.jupiterone.com/blog/cnapp-meets-the-graph-why-cloud-native-security-needs-asset-context).
- **OCSF** — [schema.ocsf.io](https://schema.ocsf.io/classes/security_finding), [ocsf.io](https://ocsf.io/).
- **Enforcement** — [Modular Monolith 2026 guide (fitness functions)](https://dev.to/x4nent/the-modular-monolith-2026-complete-guide-spring-modulith-archunit-fitness-functions-and-lessons-878), pytest-archon / import-linter.
- **Agent framework** — the `agents` skill (`wanjala:agents`) + ADR 0003 (decorator framework).
