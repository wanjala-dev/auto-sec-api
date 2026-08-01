# ADR 0011 — Per-Workspace Sample/Demo Data Mode (flag-driven, injected-but-tagged, cleanly reversible)

Status: Proposed (2026-08-01)
Relates to: ADR 0004 (Findings SSOT + cloud asset graph — the data we seed), the feature-flag system
(`components/shared_platform`), and the existing findings-only sample-data mechanism
(`components/findings/.../manage_sample_data_use_case.py`).

## Context

Auto-Sec has **high onboarding friction**: a prospect must connect an AWS account and run scans before the
product shows any value. For sales and product-led trials we want the inverse — let a workspace **explore a
fully-populated product first**, then set up live integrations when they convert. The concrete business flow
(Henry, 2026-08-01):

> Turn on sample data for a trial workspace so they can test → when they become a paying customer, turn it
> off so that workspace sets up live integrations. *"This is why I want us to bake this in now."*

**Today** a findings-only mechanism exists — `SeedSampleDataUseCase` seeds ~15 `sample.*` findings, triggered
by a standing endpoint `POST /findings/workspaces/<ws>/sample-data/` (called from an onboarding "Explore with
sample data" button). Two problems:

1. **Findings-only ⇒ half-empty.** It lights up Findings/Posture/Compliance/Attack-Coverage/Risk, but the
   **asset graph, map, attack surface, and logs/observability stay bare** — the demo looks incomplete.
2. **A loose seed endpoint is wrong for a security product.** A standing, member-accessible API that
   **injects fake findings** into a workspace is an integrity/attack surface we don't want. (Henry: *"I
   don't like having this kind of endpoint around."*)

**Requirements** (the spec):
- Per-workspace, **any** workspace — not a single hard-wired demo tenant.
- **Full realism** — findings **+ asset graph + attack paths + map + logs/observability**, as *one coherent
  fake environment*, not random rows.
- **Flag-driven on/off** — a per-workspace feature flag is the lever (trial→paying), managed centrally.
- A self-serve **onboarding "try it with sample data"** choice (early-days demo aid).
- A **top banner** whenever demo mode is on.
- **Cleanly reversible, zero contamination** — off tears everything down so the workspace goes live clean;
  sample data must never mix with real data or fire real side-effects.
- **No loose seed endpoint.**

### Grounding — research

- **Demo/sandbox mode with realistic pre-built data is the standard fix for high-friction B2B onboarding**
  (Mixpanel-style demo sandbox; PLG "explore first" activation). Feature flags routinely gate trial-vs-paid
  cohorts (default-off, per-tenant toggle, instant rollback). This validates *demo-mode-behind-a-flag*.
  ([Chameleon](https://www.chameleon.io/blog/onboarding-ux-patterns),
  [Mixpanel](https://mixpanel.com/blog/feature-flagging/),
  [Datadog](https://www.datadoghq.com/knowledge-center/feature-flags/))
- No source prescribes **clean teardown of demo data** — that's the careful engineering this ADR owns.

### Grounding — code (what already exists, verified)

- **Findings sample-seed bypasses the event bus.** `SeedSampleDataUseCase` calls `store.upsert` **directly**,
  never publishing `FindingRaised`. So **every event-driven side-effect already does NOT fire on sample
  data** — board/task creation + agent triage/routing (`finding_raised_board_handler`), **Slack alert
  delivery** (`finding_alert_delivery_handler`, the *only* finding sink), notifications. This is the isolation
  pattern to preserve and extend.
- **Query-driven read models DO include sample rows — by design** (they *are* the demo): ATT&CK coverage
  (actively recomputed by seed/clear), compliance summary, risk score, findings list, exposure summary. **No
  billing/entitlement path reads findings** (sample data can't affect billing). If exclusion is ever needed,
  the single choke point is `DjangoFindingRepository` (`_filtered` / `open_finding_asset_urns` /
  `open_finding_compliance`) + `attck_coverage_repository.open_finding_attck_tags`.
- **Marking:** sample findings carry BOTH `source="sample.*"` (`SAMPLE_SOURCE_PREFIX="sample."`) and
  `attributes.sample=True`. The banner + the clear-by-prefix both key off the `source` prefix.
- **Feature flags** resolve `user → workspace → plan-tier → global → default`. Per-workspace =
  `FeatureFlagRule(flag, scope=WORKSPACE, workspace, enabled=True)` + `bump_feature_flags_version()`. Check via
  `get_feature_flags_provider().is_feature_enabled(key, workspace_id=…)`. A `DjangoFeatureFlagSignalBridge`
  already fires on `FeatureFlagRule` post_save/post_delete (today only bumps the cache).
- **Onboarding** (`OnboardingPage.jsx`, stages create→teams→ready) already has a secondary **"Explore with
  sample data"** button in the `ready` stage that POSTs the seed endpoint. `setup-status` has no sample check.
- **Models to seed for full realism:** `cloud_graph` — `CloudAsset`, `CloudAssetEdge`, `AttackPath` (stored).
  `integrations` — `LogMetricBucket`, `LogPatternRollup` (stored; the raw LOG STREAM card reads a live S3
  window, not a table). Risk score / ATT&CK coverage / compliance / exposure are **derived** from
  findings+graph, so seeding the sources auto-populates them.

### Grounding — three concrete structural frictions (verified, must be handled)

1. **The onboarding "first scan" check silently counts sample findings.**
   `workspace_setup_query_repository._has_first_scan` returns True if *any* `Finding` row exists — it does
   **not** exclude `sample.*`. So seeding today **falsely marks "Run your first scan" complete**. Fix: add
   `.exclude(source__startswith="sample.")` (and, more generally, sample mode should not advance the live
   setup funnel). `_has_findings_triaged` is already safe (sample rows stay `OPEN`).
2. **Sample findings do NOT create graph nodes.** The finding-derived inventory adapter reads only
   `source="cloud_posture.prowler"`; `sample.cloud_posture` doesn't match. So the asset graph / attack paths /
   exposure / the risk *attack-path* component stay empty under findings-only sample mode — confirming D3:
   the graph must be **seeded directly**, not derived from sample findings.
3. **Log-metric tables have a NOT-NULL `connection` FK** to `AwsOrganizationConnection`
   (`LogMetricBucket`, `LogPatternRollup`). A pure-sample workspace has no AWS connection, so sample log rows
   need either a **sample `AwsOrganizationConnection` row** (tagged, torn down with the rest) or a schema
   relaxation. This is the biggest structural decision for sample *logs* — resolved in D3/phase 4.

Also: **no model has an `is_sample` column today** — findings carry `source="sample.*"` + `attributes.sample`.
Extending to graph/log tables needs a consistent new marker (an `is_sample` boolean or an `attributes` flag),
since those tables have no sample-distinguishing field.

## Decision

Make **demo mode a per-workspace state driven by one feature flag**, materialized as **injected-but-tagged
rows across every relevant context** through a **single coordinator**, with **hard, complete teardown** and
**strict side-effect suppression**. Replace the loose seed endpoint with the flag lifecycle + a gated
onboarding action.

### D1 — `feature.sample_data_mode` is the demo-mode SSOT and the lever

A per-workspace feature flag (default OFF, seeded in `seed_feature_flags`; add to `PROD_DISABLED_FLAGS` so
it's dark globally). Enabled for a workspace ⇒ the workspace is in **demo mode**. This is the single lever
sales flips on for a trial and off when they convert, managed with the same workspace-scoped `FeatureFlagRule`
we use for the CNAPP flags. The **banner keys off this flag** (via the flags bootstrap payload), not the
finding source — so it's robust across all subsystems, not just findings.

### D2 — The flag's lifecycle drives seed/teardown (async, idempotent) — no loose endpoint

Extend `DjangoFeatureFlagSignalBridge`: on a `FeatureFlagRule` change for `feature.sample_data_mode`,
**dispatch-after-commit** a Celery task —
- enabled → `seed_sample_data(workspace)` (idempotent: skip if already seeded / if the workspace has **real**
  data — the mutual-exclusivity guard, D4);
- disabled or rule deleted → `clear_sample_data(workspace)` (idempotent; **guarantees no orphan sample data**
  when the workspace goes live).

So "flip the flag" *is* the on/off — however it's flipped (sales admin, onboarding, a future settings toggle).
A thin `SampleDataService.enable(ws)/disable(ws)` wraps "create/remove the workspace rule" for callers. The
standing `POST/DELETE /findings/.../sample-data/` endpoint is **removed** (or hard-gated behind admin + the
flag); no member-accessible fake-data injection remains.

### D3 — Injected-but-tagged rows, one coordinator, per-context seeder ports (respects boundaries)

Seed **real DB rows** (so every existing HUD read path renders them unchanged and the demo is interactive —
you can drill the graph, triage a finding), but **every sample row is tagged**, and teardown deletes by tag.
Because the data spans bounded contexts, a cross-context **`SampleDataFacade`** (application/facades — the
canonical cross-context-orchestrator slot) calls a **`SampleDataSeederPort`** implemented per context:
- **findings** — the existing seed/clear, refactored behind the port (behavior-identical; already tagged
  `sample.` + `attributes.sample`).
- **cloud_graph** — new: seed sample `CloudAsset` + `CloudAssetEdge` + `AttackPath` (tagged `is_sample`).
- **integrations** — new: seed sample `LogMetricBucket` + `LogPatternRollup` (+ a canned log-window fixture
  for the LOG STREAM card) (tagged `is_sample`).

The facade seeds/tears down **all** contexts atomically and reports completeness. Each context owns its
marker + its delete-by-marker. (Alternative rejected: a *virtual overlay* that returns fixtures at read time —
cleaner teardown but would require branching every read path across every context and kills interactivity.
Injection + rigorous tagging is the pragmatic, realistic, boundary-respecting choice.)

**Coherent fixtures.** One curated fake AWS account: a handful of EC2/S3/IAM assets, **one public exposure →
one toxic attack path**, findings whose `asset_urn` match those assets, and log lines that mention those
services — so the graph, map, findings, ATT&CK coverage, and logs tell **one consistent story**. This fixture
authoring is the bulk of the work and the thing that makes it "realistic."

### D4 — Isolation is a first-class, security-critical invariant

- **Sample seeders write DIRECTLY, bypassing domain events / real pipelines** (the pattern findings already
  uses). Sample data therefore **never triggers a real outbound action** — no Slack/email/notification, no
  agent PR against a real repo, no real scan — and **never affects billing/entitlements**. This is an
  **invariant with a guard test** ("a workspace in demo mode fires zero outbound side-effects").
- **Query read-models include sample data by design** — that's the demo. (If we ever need "real-only"
  metrics, the D-grounding choke point makes it a one-place change.)
- **Demo ⇔ live are mutually exclusive.** Seeding guards against a workspace that has **real** data (extend
  the existing `has_real_findings` to real assets/logs). Teardown-before-live (D2) guarantees a workspace
  can't carry sample data into its live life. A workspace is *either* demo *or* live, never both.

### D5 — Onboarding "try with sample data" as a first-class choice

Promote the existing secondary button into a real onboarding choice (Henry liked it, wants it for early
days): on the create/ready path, "**Connect your cloud**" vs "**Explore with sample data**." Choosing sample
→ `SampleDataService.enable(ws)` (flag on → seed) → enter the HUD in demo mode with the banner. When they're
ready to go live, "clear sample data" (banner) or the sales flip → flag off → teardown → connect for real.

## Consequences

- One lever (`feature.sample_data_mode`) for the whole trial→paying lifecycle; adding a new demo surface = a
  new per-context seeder behind the port, nothing else.
- The demo becomes *complete* (graph + map + logs), not findings-only.
- The loose fake-data endpoint is gone — injection happens only through the gated flag lifecycle.
- Cost: fixture authoring (the coherent fake account) + per-context seeders + the teardown/guard tests + the
  banner/onboarding rewire. Mitigated by the strangler phases (findings keeps working throughout).
- Risk: injected rows in real tables. Mitigated by rigorous tagging, the direct-write side-effect bypass, the
  mutual-exclusivity guard, and hard teardown — all test-guarded.

## Non-goals

- **Not** a virtual/overlay demo (we inject tagged rows, then delete them).
- **Not** seeding real scans or real integrations, and **not** running agents/notifications on sample data.
- **Not** mixing demo + live in one workspace.
- **Not** a self-serve seed endpoint for arbitrary workspaces (the flag + gated onboarding are the only
  triggers).
- **Not** billing/metering demo workspaces as real usage.

## Implementation plan (strangler — each phase ships on its own; this ADR is the spec)

1. **Flag + SSOT + kill the endpoint.** Seed `feature.sample_data_mode` (default off, prod-disabled). Migrate
   the banner to key off the flag (flags bootstrap). Remove/hard-gate `POST/DELETE …/sample-data/`; wire the
   onboarding button + banner-clear to `SampleDataService.enable/disable`. Signal-bridge → async seed/teardown
   (findings only for now — behavior-identical). **Fix the `_has_first_scan` leak** (exclude `sample.`) so demo
   mode doesn't falsely advance the live setup funnel. Guard test: demo mode fires zero outbound side-effects.
2. **Coordinator + ports.** `SampleDataFacade` + `SampleDataSeederPort`; refactor the findings seed/clear
   behind the port. Idempotency + completeness + mutual-exclusivity guard tests.
3. **Cloud-graph seeder.** Sample `CloudAsset`/`CloudAssetEdge`/`AttackPath` (tagged), coherent with the
   sample findings → asset graph, map, attack surface, risk gauge populate.
4. **Integrations seeder.** Sample `LogMetricBucket`/`LogPatternRollup` + a canned log-window → observability
   + LOG STREAM populate. **Decide the `connection`-FK friction first** (both tables NOT-NULL FK
   `AwsOrganizationConnection`): seed a tagged sample connection row (torn down with the rest) vs. relax the
   FK. Recommend the sample-connection row — keeps the schema honest and the teardown uniform.
5. **Onboarding first-class choice** + go-live teardown polish; the coherent fixture set finalized.
6. **Hardening.** Teardown-completeness (no orphans across contexts) + side-effect-suppression invariant tests;
   `setup-status` optionally learns a "sample data active" check.

Build only after review. Phases 1–2 re-platform the existing findings demo onto the flag/coordinator without
new fixtures; 3–5 add the realism; 6 proves the safety.
