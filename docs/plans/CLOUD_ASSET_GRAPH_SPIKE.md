# Cloud Asset Graph — Spike & Design

**Date:** 2026-07-23. **Status:** Spike design (no production code yet). **Owner-decision needed:** substrate.
**Parent strategy:** the "Auto-Sec → CNAPP" feasibility assessment (§5 Phase B — the asset graph).
**Depends on / relates to:** `SECURITY_POSTURE_VISION_2026-07-20.md` (Phase 3 Prowler),
`INTEGRATIONS_AWS_POC_2026-07-17.md` (onboarding + STS), `POC_CLOUDTRAIL_TRIAGE_2026-07-17.md` (CDR spine).

---

## 1. Context — why a graph, and why now

The CNAPP assessment found that the single artifact separating "AI-SOC + a scanner" from "a CNAPP" is a
**code-to-cloud asset/risk graph**: an inventory of cloud resources + the relationships between them, over
which you rank **toxic combinations** (e.g. *internet-exposed* → *unpatched* → *over-privileged identity* →
*reachable sensitive data*). It is Wiz's whole moat, and it is the one genuinely new subsystem we lack.

**The graph is dual-use** — which is why it's the right first build even before committing to a full CNAPP:
1. **Improves the SOC we already ship today.** The triage agent's findings currently carry a shallow
   `blast_radius` dict computed from the log window (`ErrorFinding.blast_radius`). With a graph, triage can
   answer *"is the affected service internet-exposed? what identity/role can reach it? what's downstream?"* —
   real blast-radius, not window-locals. That lifts finding quality **now**.
2. **Is the CNAPP foundation.** Every later pillar (CIEM entitlement paths, CWPP vuln reachability, attack
   paths) correlates onto this graph.

So even if we never adopt the "CNAPP" label, the graph pays for itself as triage context (no-shortcuts:
not a speculative throwaway).

## 2. Goal of the spike (what "done" proves)

A thin, feature-flagged proof that answers **yes** to all three:
- **G1 — Inventory:** we can enumerate a linked account's core resources + relationships into a persistent
  store, using the STS assume-role plumbing we already have (no new credential path).
- **G2 — Attack-path queries:** we can answer **2–3 toxic-combination queries** (below) from that store.
- **G3 — Agent consumption:** the `triage_agent` (and later `cloud_posture_agent`) can read the graph via a
  tool and cite it in a finding — landing on the board through the **existing** `persist_finding_as_task`
  path (no new finding plumbing).

Explicitly **out of scope** for the spike: full multi-cloud, DSPM/data reachability, runtime signals, a UI,
and any write-back. Prove the graph + queries + one agent tool on **AWS only**, one account.

## 3. Substrate decision (the spike's core question)

| Option | What it is | Fit | Verdict |
|---|---|---|---|
| **A — Bootstrap from Prowler output** | Phase A (Prowler) already assumes-role and enumerates the resources it checks; its JSON/OCSF output carries resources + some relationships | **Zero new infra/deps** — reuses data we're already collecting; but only covers resources Prowler checks (not a complete inventory) | ✅ **Spike path** — cheapest proof, reuses Phase A |
| **B — CloudQuery** | ELT that *syncs* cloud resources into normalized **Postgres** tables (we already run Postgres/pgvector) | Complete, persistent inventory in the DB we already have; scheduled sync fits the detector-cycle cadence | ✅ **Production substrate** (after value proven) — **⚠ licensing due-diligence required** (CloudQuery relicensed plugins in 2024; verify the CLI + AWS plugin license before vendoring, same rigor as the Prowler Apache-2.0 check) |
| **C — Steampipe / Powerpipe** | *Live* SQL over cloud APIs via FDW; no persistent store by default | Great for ad-hoc compliance queries; poor for a persistent graph the agent + findings correlate onto | 🟡 Optional adjunct for ad-hoc posture Q&A, not the graph store |

**Recommendation:** build the spike on **Option A** (derive the graph from Prowler's Phase-A output — no new
dependency), design the models so **Option B (CloudQuery)** can backfill a complete inventory later without a
schema change. Decide A→B promotion once G1–G3 prove the graph earns its keep.

## 4. Data model — a new `cloud_graph` bounded context

Follow `bounded-context-structure.md`. Two ORM aggregates (in `infrastructure/persistence/cloud_graph/`),
mirroring how `integrations` models are laid out, workspace-scoped like everything else:

- **`CloudAsset`** — one row per resource. Fields (PK → FK → data → metadata):
  `workspace` (FK), `aws_account_link` (FK → `AwsAccountLink`), `provider` (aws|gcp|azure),
  `resource_type` (e.g. `aws_ec2_instance`, `aws_iam_role`, `aws_s3_bucket`, `aws_security_group`),
  `arn`/`resource_id`, `region`, `name`, `attributes` (JSONB — the normalized config),
  `exposure` (derived: `public`|`internal`|`private`), `first_seen`/`last_seen`, `is_deleted`.
  Unique: `(aws_account_link, arn)`.
- **`CloudAssetEdge`** — one row per typed relationship. `workspace`, `src_asset` (FK), `dst_asset` (FK),
  `relation` (e.g. `can_assume`, `attached_to`, `allows_ingress_from`, `has_policy`, `in_subnet`,
  `routes_to_igw`, `reads_bucket`), `attributes` (JSONB), `last_seen`. Unique: `(src_asset, dst_asset, relation)`.

Postgres relations are the graph for the spike (recursive CTEs cover 2–4 hop paths — enough to prove value;
no graph DB). Revisit a dedicated graph store only if path queries outgrow recursive CTEs.

## 5. Ingestion — reuse the existing credential + cadence rails

- **Credentials:** reuse the exact assume-role pattern already in
  `components/integrations/application/log_ingest_service.py::_assume_role_s3_client` /
  `.../adapters/sts_org_adapter.py` — per-`AwsAccountLink`, `ExternalId`, ephemeral creds. **No new
  credential path.** (Prowler in Phase A uses the same role; the graph builder consumes its output.)
- **Cadence:** a new **detector** on the existing detector cycle (`detector_cycle.py`) — `cloud_graph.sync`
  — runs nightly like the posture detectors, materializes/updates `CloudAsset`/`CloudAssetEdge` from the
  Phase-A Prowler run (Option A). Idempotent upserts keyed on `arn` / edge tuple.
- **Ports:** `application/ports/asset_inventory_port.py` (`sync_account() -> AssetGraphDelta`) with a
  `ProwlerDerivedInventoryAdapter` (spike) and, later, a `CloudQueryInventoryAdapter` (production) — swap the
  adapter, not the caller (architecture-manifesto Rule 5).

## 6. The 2–3 attack-path queries the spike must answer

Deterministic queries (recursive CTEs), each returning a ranked *toxic combination*, each mapped to an
evidence contract:
1. **Public compute with a powerful role:** `aws_ec2_instance` where `exposure=public`
   `--attached_to-->` `aws_iam_role` `--has_policy-->` policy with `*`/admin. → *"internet-reachable box can
   act as admin."*
2. **Open ingress to sensitive port:** `aws_security_group` `--allows_ingress_from 0.0.0.0/0-->` on 22/3389/DB
   ports `--attached_to-->` a running instance. → *"world-open management/DB port."*
3. **Public bucket reachable by a broad principal:** `aws_s3_bucket` where `exposure=public` OR
   `--reads_bucket--` from a role assumable across accounts. → *"data exposure path."*

Each query result becomes a **finding** via the reuse pattern (next section). Prioritization = number/severity
of legs in the path (the agent-native "attack path score" — Phase D turns this into LLM-ranked narrative).

## 7. Agent consumption + findings — the #41/#47 reuse pattern (no new plumbing)

- **New source types** added to `ROUTABLE_SOURCE_TYPES` (`logwatch.py`): `ai.cloud_exposure` (+ later
  `ai.attack_path`). *That's the whole routing change* — the router (`AiFindingRouterDetector`) dispatches to
  the declaring specialist unchanged.
- **Findings:** the `cloud_graph.sync` detector emits `DetectorResult`s (the same dataclass every detector
  uses) with an evidence contract (path legs = `evidence`, path score = `impact_score`) → the existing
  `specialist_persistence_service.py::persist_finding_as_task` lands them on the board with provenance. **No
  new finding model.**
- **A read tool for the agents:** `query_asset_graph(resource_id | service)` on the `triage_agent` (and the
  future `cloud_posture_agent`) — returns exposure, attached identities, ingress, downstream. Triage cites it
  to replace the shallow window-local `blast_radius` with a real one. Byte-stable tool name (constitutional).

## 8. Architecture placement (respect the rules)

- New context `components/cloud_graph/` (api/application/domain/infrastructure/mappers/tests per
  `bounded-context-structure.md`); ORM in `infrastructure/persistence/cloud_graph/` (never in `components/`).
- Cross-context: consume `AwsAccountLink` via `integrations`' public port/entity, **not** its infrastructure
  (architecture-manifesto Rule 3). Emit findings via the shared `persist_finding_as_task` seam (DRY).
- Feature-flagged (`shared_platform` flags) from day one, like every in-progress surface.

## 9. Scope, verification, risks

**Spike deliverable:** the two models + one `ProwlerDerivedInventoryAdapter` + the `cloud_graph.sync`
detector + the three CTE queries + the `query_asset_graph` tool + one `ai.cloud_exposure` finding path,
behind a flag, AWS/one-account.

**Verification (end-to-end, no write-back):**
- Seed a fixture account (or a Prowler sample JSON) → run `cloud_graph.sync` → assert `CloudAsset`/`Edge`
  rows materialize idempotently (run twice → no dupes; the existing checkpoint/idempotency discipline).
- Run each CTE query against the seeded fixture → assert the known toxic path is returned + ranked.
- Trigger the detector cycle → assert an `ai.cloud_exposure` card lands on the board with the path as
  evidence + provenance (the existing detector-cycle integration-test pattern).
- Call `query_asset_graph` in an `AgentTestCase` (stubbed LLM) → assert it returns the exposure/identity
  facts the triage prompt will cite.

**Risks / open questions:**
- **CloudQuery licensing** (Option B) — verify before any vendoring; if it fails due-diligence, stay on
  Option A + boto3 describe-calls for completeness.
- **Prowler resource coverage** (Option A) — Prowler surfaces resources it *checks*, not a full inventory;
  acceptable for the spike, a gap for production (→ Option B).
- **Graph scale** — recursive CTEs are fine at spike scale; large orgs may need materialized path tables or a
  graph store. Defer until measured.
- **Operator dependency** — same read-only IAM audit role Phase A waits on (Henry's infra call). The spike
  can run on a fixture until that lands.

## 10. Sequencing note

This spike is **gated behind, and best built on, Phase A (Prowler)** — Option A literally consumes Phase A's
output. Practical order: land Phase A (Prowler CSPM) → spike the graph on its output → decide CloudQuery
promotion → Phase C engines (Trivy/Checkov) correlate onto the proven graph. See the Prowler plan:
`CLOUD_POSTURE_PROWLER_INTEGRATION_PLAN.md`.

## 11. Later — graph visualization (HUD), reuse don't rebuild

The spike is headless (queries + a tool); the graph *HUD* comes after. **Do not hand-roll a graph canvas.**
The frontend (literacyseed / `auto-sec-frontend`) already ships a **workflow builder canvas** (the
`components/workflow` builder — canvas, nodes, edges/leaves, node palette, pan/zoom) that renders a
node-edge graph today. Borrow those reusable node/edge primitives for the asset-graph / attack-path HUD and
restyle them to the V2 SOC HUD, rather than standing up a second graph-rendering stack (per `dry-reuse.md`
and the frontend component-catalog rule). Invoke `/frontend-reuse` before building any graph UI. This is a
pointer for the visualization phase — the spike itself needs no UI.
