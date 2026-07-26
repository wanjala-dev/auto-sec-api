# ADR 0005 — Cloud asset-graph substrate: Prowler-derived nodes + boto3-derived edges (not CloudQuery)

**Status:** Accepted (2026-07-26). Unblocks the attack-path slice of item #7.
**Context:** ADR 0004 (CNAPP unified finding + asset-graph spine), `docs/plans/CLOUD_ASSET_GRAPH_SPIKE.md`
(the spike design, which deferred this decision as "owner-decision needed: substrate").
**Supersedes the open question in:** spike §3 (Option A vs B).

---

## Context

The cloud asset graph (`components/cloud_graph`) has landed its foundation (#107), Prowler-derived
node ingestion (#109), and the `query_asset_graph` triage tool (#112). The remaining piece — **attack-path
correlation** (the CNAPP differentiator: toxic combinations like *public-exposed → over-privileged → reachable
sensitive data*) — needs **typed edges** between assets, which the Prowler-finding-derived nodes don't carry
(Prowler findings are per-resource checks, not relationships). The spike flagged three substrate options and
deferred the choice:

- **A** — stay Prowler + add targeted **boto3 `describe`** calls to derive edges (in-stack, we own it).
- **B** — adopt **CloudQuery** (ELT sync of cloud config into Postgres).
- **C** — Steampipe (live SQL over cloud APIs, no persistent store) — already rejected for a persistent graph.

## Decision

**Adopt Option A: derive the asset graph from our own Prowler-derived nodes + targeted boto3 `describe`/`list`
calls for edges, stored in Postgres and queried with recursive CTEs (per ADR-0004 D8, no graph DB).**

## Rationale (research-grounded, 2026-07-26)

1. **CloudQuery is now fully commercial.** Its official AWS/GCP/Azure plugins moved from free to paid, and its
   model is **per-row-synced, billed annually** ([pricing](https://www.cloudquery.io/pricing),
   [plugins moving to paid](https://www.cloudquery.io/blog/cloudquery-official-free-plugins-moving-to-paid)).
   For a pre-revenue product syncing many rows across *customer* accounts, that is a real recurring cost +
   an external vendor dependency on the security-critical data path. Option A adds **zero new cost or deps**.
2. **boto3-derived graphs are the industry-standard approach.** Cartography, Steampipe's relationship graphs,
   and aws-visualizer all pull via the AWS SDK/CLI and model exactly the edges our CTE queries need —
   `can_assume` (IAM trust), `attached_to` (instance-profile → role), `allows_ingress_from` (security-group
   ingress), and public exposure ([Steampipe AWS relationship graphs](https://steampipe.io/blog/aws-relationship-graphs),
   [visualizing AWS attack paths](https://undercodetesting.com/visualizing-aws-attack-paths-how-to-map-iam-privilege-escalation-lateral-movement-like-a-pro-video/)).
   The three spike attack-path queries (§6) are all reachable from standard describe/list calls.
3. **Stays in-stack, no new credential path.** Option A reuses the existing STS assume-role plumbing
   (`components/integrations/.../sts_org_adapter.py`, `log_ingest_service._assume_role_s3_client`) — same
   role Prowler already uses — so no new IAM ask on the customer (spike §5).
4. **Fits the persistence decision we already made.** Edges live in the existing `CloudAssetEdge` Postgres
   table (#107); attack-path is a recursive CTE (ADR-0004 D8). The graph-native OSS alternative
   (**Cartography**) is **Neo4j-based**, which ADR-0004 D8 explicitly rejects — adopting it would reverse a
   standing decision and add a graph-DB to operate.
5. **We own the risk logic.** The "toxic combination" scoring is our differentiator (the AI-SOC value layer on
   top of the graph); deriving edges ourselves keeps that logic in-house and swappable — the
   `AssetInventoryPort` (#109) already lets a CloudQuery/`boto3` adapter be swapped in later **without touching
   the caller** if the economics ever change.

## Consequences

**Positive:** no new vendor/cost/credential; consistent with ADR-0004 (Postgres CTE, OCSF spine, port-swappable
inventory); reuses the assume-role rails; the edge-derivation + risk logic stays owned.

**Negative / accepted:**
- **We build and maintain the boto3 collectors** for each resource/edge type (EC2, IAM, security groups, S3
  to start). This is more code than pointing CloudQuery at an account — accepted, because it's the security
  core and keeps us dependency-free.
- **Coverage is what we collect.** Prowler nodes cover failing-check resources; boto3 adds the specific
  resources/edges the attack-path queries need — not a *complete* inventory (that's Wiz/Orca's agentless moat,
  which per ADR-0004 we deliberately do not chase). Good enough for ranked toxic-combinations; revisit if a
  complete inventory is ever required.
- **API-rate + scale:** describe/list calls are rate-limited; collectors must page + back off and run on the
  existing cadence (the `cloud_graph.sync` detector, self-leased). Materialize attack-paths in a background
  job (ADR-0004 §6), never inline.

## Build plan (attack-path on Option A — phased, each shippable)

1. **boto3 edge collector** behind a new `AssetEdgeCollectorPort` (adapter under `components/cloud_graph`
   or `components/integrations`), assume-role, paging + backoff. Start with the edges the first query needs:
   `attached_to` (EC2 instance → instance-profile → IAM role) and `has_policy` (role → admin/`*`). Upsert
   `CloudAssetEdge` idempotently (the store already supports it).
2. **First attack-path CTE query** — "public compute with a powerful role" (spike §6.1): recursive CTE over
   `CloudAsset`/`CloudAssetEdge` returning the ranked toxic path.
3. **Emit the finding** — the `cloud_graph.sync` detector turns each path into an `ai.cloud_exposure`
   `DetectorResult` via the existing `persist_finding_as_task` seam (path legs = evidence, path length/severity
   = impact_score); add `ai.cloud_exposure` to `ROUTABLE_SOURCE_TYPES`. Emit the (currently dead)
   `AttackPathDetected` shared-kernel event.
4. **Remaining two queries** — world-open ingress; public bucket reachable by a broad principal (spike §6.2/§6.3),
   each adding its edge collectors.
5. **Background materialization** of attack-paths + contextual risk into a read table (ADR-0004 §6) → CQRS read →
   the HUD.

All feature-flagged (`feature.cloud_asset_graph`, already seeded off).
