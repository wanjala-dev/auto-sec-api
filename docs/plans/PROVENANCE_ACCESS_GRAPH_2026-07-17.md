# Provenance & Access Graph — who (human / service account / AI agent / vendor) touched what, when, with what permission

Status: **PLAN / not started** · Owner: Henry · Created: 2026-07-17

## Context — the pitch (Henry)

In most orgs you can't answer, with confidence: *who did what, when, in each system* — and you trust it even less across **vendors/integrations**. autosec should make that answerable. Three questions, one graph:

1. **Vendor/integration blast-radius.** For every connected app — AWS, Slack, Google Workspace, Okta, Vanta, Tableau, GitHub, … — map *what it is actually doing in our ecosystem*: what scopes/permissions it holds, what it can **read**, what it can **execute**. "If this vendor is compromised, what can it reach?"
2. **Access review** (the Okta/Vanta table, but unified): who has access to what, which roles, all employees + **service accounts** + **AI systems** — not just humans.
3. **Provenance tree ("hall tree").** For any actor — a human employee, a service account, or an **AI agent** — expand what they *touched*: which resources, which actions, when. Provenance for *everybody*, including AI agents (the timely, differentiated part — Okta does humans; nobody does humans + service accounts + AI agents in one model).

This is autosec's third pillar next to the **triage board** and **AI observability**.

## Reuse first — this extends existing machinery, it is NOT a new parallel store (DRY)

| Capability | Already in the fork | How the graph uses it |
|---|---|---|
| **Append-only audit trail** | `components/audit` + `infrastructure/persistence/audit/models.py` — `EntityAuditLog`: nullable `actor` FK, polymorphic target (`content_type` + `object_id`), `field_name`/old/new, `workspace`, `created_at`, indexed by actor + entity | This is the **internal provenance event store**. A ProvenanceEvent is a generalization of an audit row; internal actions already land here. |
| **AI-actor actions** | `infrastructure/persistence/ai/actions` (+ detectors) + `AIActionCreated` events | AI agents as first-class actors — their actions are provenance edges. |
| **Human provenance** | identity sessions + `me/login-activity` + org `login-activity`/`sessions` (commits 781–785), `WorkspaceMembership.role` | Human actors + their internal access grants + session/login provenance. |
| **Vendor connectors** | `docs/plans/INTEGRATIONS_AWS_POC_2026-07-17.md` (read-only cross-account IAM role + ExternalId; GuardDuty). Not yet built. | Each connector gains TWO extra pulls: (a) the vendor's own granted scopes/permissions, (b) the system's access + audit logs (CloudTrail, Okta System Log, Google Workspace audit, Slack audit logs). |

New code is the **graph model + query layer + ingestion adapters + a HUD graph surface** — everything underneath already exists.

## Domain model — one bounded context, `components/provenance/`

Unified graph over four node/edge types (workspace-scoped, append-only):

- **Actor** (node) — `type ∈ {human, service_account, ai_agent, vendor_integration}`, identity, source system, status. A human maps to `CustomUser`; an AI agent to an agent id; a vendor to an integration.
- **Resource** (node) — a thing acted upon: a system, data store, repo, channel, bucket, record. `type` + external ref + source system.
- **Grant** (permission edge) — `Actor → Resource` with a permission set (`read` / `write` / `execute` / `admin`), scope, and **source** (which system granted it, e.g. an IAM policy, an OAuth scope, an Okta role). This is the "what can they read/execute" map — the *potential*.
- **ProvenanceEvent** (action edge) — `Actor → Resource` "did X at time T," provenance metadata (ip, session, request id, tool). This is the *actual*. Internal ones are `EntityAuditLog` rows; external ones are ingested from vendor audit logs.

The **graph = Actors + Resources + Grants (potential) + ProvenanceEvents (actual)**. The gap between potential and actual is itself a signal (over-permissioned vendor that never uses 90% of its scopes → least-privilege recommendation → a finding on the triage board).

## Query surface (`application/queries/`, CQRS, read-only, workspace-scoped)

- **Vendor blast-radius:** given a vendor actor → all Grants (what it can reach) + recent ProvenanceEvents (what it actually did).
- **Access review:** given a Resource → all actors with a Grant, grouped by permission tier.
- **Provenance tree ("hall tree"):** given an actor → tree of resources touched → drill into each resource's events over a window.
- **Least-privilege / drift:** Grants with zero ProvenanceEvents in N days (unused permissions); new Grants since last review (privilege creep).

## HUD surface (reuse the V2 graph aesthetic — `autosec-v2-hud` skill)

- **Access graph** — an actor→resource node graph. Reuse the canvas/graph chops already in the design system (the `CoreCanvas` hex ring; literacyseed's `Chart/d3/AiAgentGraph` is portable). Actor nodes colored by type (human/service/AI/vendor); edges = grants; thickness/heat = event volume.
- **Hall-tree panel** — expand an actor → tree of what it touched (the provenance drill-down), HUD-styled.
- **Vendor cards** — one per integration: scopes held, read/execute reach, last-active, unused-permission count. Lives in **Settings ▸ Integrations** (shared with the integrations plan).
- Ties to the other pillars: a least-privilege / anomalous-access finding becomes a **triage-board task** assigned to a member; a spike in a vendor's actions glows an alert hex.

## Ingestion (adapters, per source — least-privilege, read-only)

Each vendor connector implements two ports: `fetch_permission_inventory()` (grants) and `fetch_activity_log(window)` (events). First targets: **AWS** (IAM policies + CloudTrail — pairs with the GuardDuty connector already planned), **Okta** (users/roles + System Log), **Google Workspace** (admin audit), **Slack** (audit logs API). All read-only, all behind the same cross-account/OAuth-scoped, ExternalId-guarded pattern as the integrations plan.

## Phasing

- **Slice 0 (internal-only, zero new integrations):** ship the `provenance` context + graph model + query layer, backfilled from what we ALREADY have — `EntityAuditLog` (internal actions), `ai/actions` (AI agents), identity sessions/roles (humans + internal grants). Gives a working actor→resource graph for autosec's *own* actors on day one, no external creds. Proves the model.
- **Slice 1:** AWS connector — IAM grant inventory + CloudTrail events → first external actors (vendor + service accounts) on the graph. Least-privilege drift detection → triage findings.
- **Slice 2:** Okta + Google Workspace + Slack connectors → full cross-vendor access review + hall-tree.
- **Slice 3:** potential-vs-actual analytics (unused-scope least-privilege recommendations, privilege-creep alerts) + scheduled access-review reports.

## Gating

New context behind a feature flag from day one (`feature.provenance_graph`, off in prod, per-workspace opt-in) per the scope-freeze discipline. Read-only everywhere — this NEVER mutates a vendor's permissions, it only observes.

## Open questions

- Graph store: start on Postgres (adjacency tables + recursive CTE for the hall-tree) or reach for pgvector-adjacent graph tooling? Prefer Postgres first — the audit trail already lives there; add a graph store only if traversal depth demands it.
- Actor identity resolution across systems (same human = Okta user = Google user = GitHub login) — a correlation/merge problem (mirrors the contacts-merge pattern on the Wanjala side).
- Retention/volume of external audit-log ingestion (CloudTrail is high-volume) — sample vs full, TTL.

## References

- Internal: `components/audit`, `infrastructure/persistence/audit/models.py`, `infrastructure/persistence/ai/actions`, identity sessions/login-activity (commits 781–785), `docs/plans/INTEGRATIONS_AWS_POC_2026-07-17.md`, `docs/plans/AI_OBSERVABILITY_MODEL_HEALTH_2026-07-17.md`.
- External: least-privilege / access-graph prior art (Okta, Vanta, BloodHound's identity-attack-path graph as a UX reference for the actor→resource graph).
