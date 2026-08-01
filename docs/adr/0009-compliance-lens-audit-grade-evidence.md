# ADR 0009 — Compliance as a Third Lens: Audit-Grade Evidence with Provenance

Status: Proposed (2026-07-31)

## Context

Auto-Sec's thesis is **one graph, read through lenses**: blue (defend) and red (attack) already read the
same Findings SSOT + cloud asset graph. A second operator interview (Andrea — a solo security engineer who
also owns compliance at a small startup, mid-flight on a **SOC 2 Type II** with Vanta; see
`docs/product/STATE_AND_VISION.md` §2.2) surfaced a **third co-equal lens: _prove_ (compliance)** — read
the same graph, map it to framework controls, and emit **audit-grade evidence**.

His core insight, verbatim: *"You gotta look at a piece of evidence — where it comes from, how it was made,
when it was made, and if it's the original report. That's what gives it credence."* A raw report an auditor
can't trace ("it doesn't say when it was generated, what was scanned, what parameters, if there was
filtration, what source system generated it") is worthless. **Provenance is the product.**

The unfair advantage: **evidence aggregators (Vanta/Drata) collect evidence _from_ other tools, so their
provenance is second-hand.** Auto-Sec _generates_ the scans itself (Prowler/Trivy/log detection/asset graph),
so it can stamp first-party provenance at the moment of generation. And the wedge is explicitly **not** a
first-timer onboarding wizard (his money quote: *"Vanta helps you the first time; after that, why do you even
need a platform?"* — our own org rolled its own for the same reason) — it's **automation + provenance for
teams past their first audit**.

### What already exists (grounding — reuse, don't rebuild)

- **Compliance tagging + failing-controls summary** — `ComplianceSummaryView`
  (`GET /findings/workspaces/<ws>/compliance-summary/`) rolls up **distinct failing controls** per curated
  framework (CIS, PCI-DSS, SOC 2, ISO 27001, HIPAA, NIST, FedRAMP) from open findings' compliance tags.
  Notably: *"Real failures only — no fabricated pass %"* — the same no-faked-evidence discipline this ADR
  extends. This is **posture** ("what's failing"), not **evidence** ("prove it, with provenance").
- **Immutable audit trail** — `components/audit` (`EntityAuditLog`). The provenance/lineage substrate.
- **Provenance / access graph** — `components/provenance` (full context), gated behind
  `feature.provenance_graph` (dark). "Who — human / service-account / AI-agent / vendor — can touch what."
  Andrea's *unmet* need ("access inventory / who-has-access isn't set up, and it's expensive").
- **AI governance** — an `ai_governance` service + specialist agent (`components/agents`).
- **Orchestration primitives** — `workflow` engine, `sign_off` approval gate, `notifications` + Slack.

### The automation boundary (from the interview — do not over-promise)

- **API-able evidence → automate** (cloud posture, asset inventory, access graph, config).
- **No-API systems → manual** (login, find page, screenshot). Orchestrate + track; don't fake.
- **SOC 2 Type II random sampling → always manual** (auditor picks N random change-requests). Not
  automatable; the platform assists retrieval, it does not answer the sample for the auditor.
- **Cross-source corroboration** strengthens evidence (his MDM-list × antivirus-console trick: one report
  proves the inventory *and* AV coverage).

## Decision

Add a **compliance (prove) lens** as a **new bounded context** that reads the existing graph and reuses the
existing primitives — never a parallel silo (hub-and-spoke; ADR 0004). The load-bearing seams mirror the
`ScannerPort` / `LogSourcePort` pattern (ADR 0006 / 0008): a port + pluggable adapters + a registry.

### D1 — Compliance reads the one graph; it does not fork it

The lens consumes the Findings SSOT, asset/access graph, and existing compliance tags. Framework/control
knowledge lives in a **control catalog**; the lens correlates controls ↔ findings ↔ assets ↔ evidence. No
second findings store, no per-framework tables beyond the catalog.

### D2 — `Evidence` artifact with a first-class **provenance envelope**

An immutable `Evidence` record: `{ id, workspace, control_ref(s), artifact (or ref), content_hash,
provenance }` where **`provenance` is required** and carries: `generated_at`, `source_system`
(prowler/trivy/logwatch/asset_graph/provenance_graph/manual/…), `scope` (account/region/asset set),
`parameters` (scan config), `filters`, `collection_method` (api | mdm | manual_screenshot | export), and
`lineage` (original vs derived, and from which run/finding). Evidence is **append-only** and linked to the
audit trail. No evidence without provenance — the schema forbids it.

### D3 — `EvidenceCollectorPort` + registry (control → evidence)

A port `collect(control, scope) -> [Evidence]` with per-source adapters, registered by kind (mirrors
`LogSourceProvider`). First adapters wrap what Auto-Sec already generates: `PostureEvidenceCollector`
(Prowler snapshots), `AssetInventoryEvidenceCollector` (cloud_graph), `AccessReviewEvidenceCollector`
(provenance graph), `AiGovernanceEvidenceCollector`. Each stamps D2 provenance at collection time. A control
with no automatable collector is marked **manual** (see D6).

### D4 — Provenance generated at the source (the differentiator)

Because Auto-Sec runs the scan, the collector stamps provenance from the *actual run* (job id, params, time,
scope), not reconstructed after the fact. This is the property aggregators structurally cannot match; it is
the reason to build this here rather than integrate a GRC tool.

### D5 — Access-review evidence un-darks `feature.provenance_graph`

The access/provenance graph becomes an evidence source (who-can-touch-what → access-review control). This is
the concrete first customer value for un-darking that flag (per-workspace, like the CNAPP flags — never a
global `default_enabled` flip).

### D6 — Honest automation boundary, encoded

Each control carries a `collection_mode`: `automated` | `assisted` | `manual`. `manual`/`assisted` controls
enter the **audit-cycle workflow** (D7) with per-control **instructions** ("export report X / screenshot Y")
rather than a fabricated artifact. Type II sampling is explicitly `manual`. Mirrors "no fabricated pass %".

### D7 — Audit-cycle orchestration on existing primitives (kill the spreadsheet)

Reuse `workflow` + `sign_off` + `notifications` + Slack: assign controls to owners, kick off a channel, put
instructions on each control, track collection status (pending / collected / approved), over-share context.
No new workflow engine — a compliance *facade* over the existing one.

### D8 — Evidence export package (auditor-facing)

Per control/framework, assemble an **evidence package**: the artifacts + a **provenance manifest** (D2 fields
per artifact) + a generation timestamp for the package itself. This is the auditor-acceptable output; it is
the thing a raw report is not.

### D9 — Shadow-AI monitoring feeds AI-governance evidence

Extend the `ai_governance` specialist to surface "who is talking to known AI platforms" (monitor; enforce is
a later bonus) and emit it as governance-control evidence.

## Consequences

- The **prove** lens compounds the graph investment — a third buyer (the compliance-owning operator) with no
  new data model beyond `Evidence` + the control catalog.
- Provenance-at-source is a defensible differentiator vs Vanta/Drata for repeat-audit teams.
- `feature.provenance_graph` finally has a customer-facing reason to ship.
- Risk: compliance is a crowded, sales-heavy market; this ADR scopes the *engine*, not a full GRC suite
  (see Non-goals). Validate with Andrea (offered to test) before deep investment — per Tom's "don't
  overbuild; validate first" (§2.1).

## Non-goals

- **Not** a full GRC/policy-management suite (policy authoring, vendor risk, personnel/training records are
  out — integrate, don't rebuild).
- **Not** replacing the auditor or auto-answering Type II samples.
- **Not** a first-timer onboarding wizard (that's the incumbents' game).
- **Not** faking evidence or pass percentages — ever.

## Implementation plan (strangler — each phase ships on its own; this ADR is the spec)

1. **Evidence model + provenance envelope** (D2) — new `compliance` bounded context + `Evidence` persistence,
   linked to the audit trail. Stamp provenance on one existing source (posture) end-to-end.
2. **Control catalog + `EvidenceCollectorPort` + registry** (D1, D3) — catalog seeded for **SOC 2** first;
   `PostureEvidenceCollector` + `AssetInventoryEvidenceCollector` mapping to controls.
3. **Access-review evidence** (D5) — `AccessReviewEvidenceCollector`; un-dark `feature.provenance_graph`
   per-workspace.
4. **Audit-cycle workflow** (D6, D7) — control assignment + instructions + collection tracking over
   `workflow`/`sign_off`/Slack.
5. **Evidence export package** (D8) — provenance manifest + bundle, per control/framework.
6. **Shadow-AI + AI-governance evidence** (D9).
7. **HUD "prove" lens** — surface controls → evidence → export in the cockpit (third lens alongside
   blue/red); + later, manual/push evidence intake for no-API sources.

Phases 1–2 prove the seam (like S3 did for `LogSourcePort`); 3+ generalize. Build only after a validation
pass with a real compliance operator.
