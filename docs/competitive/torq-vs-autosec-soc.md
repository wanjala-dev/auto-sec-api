# Torq vs autosec SOC Arm — Competitive Teardown

> **What this is.** A mechanism-level competitive analysis of **Torq** (SOC hyperautomation
> / "AI SOC") against **autosec's** SOC arm (the deep-agent + workflow layer of our CNAPP).
> Torq is the SOC benchmark; autosec is our product. Reader: the autosec founder/engineer.
>
> **Method.** Torq claims are grounded in its public KB (kb.torq.io), developer docs
> (developers.torq.io), and torq.io product/blog/product-update pages, mined July 2026.
> autosec claims are read from this repo's code (paths cited inline), not benchmarked at
> scale. Produced by a multi-agent research + codebase-mapping workflow; see
> `docs/plans/ioc-enrichment-node-and-threat-intel.md` for the item-#3 build spec that
> falls out of §5/§7.

> **Confidence-of-claims note (applies throughout).** Every Torq performance/ROI/scale
> number here (~90–95% Tier-1 closed, ~5x throughput, ~90% investigation reduction,
> connector counts, named-customer proof) is **vendor- or vendor-comparison-marketing-
> sourced** — Torq publishes no false-positive rates and no accuracy/precision benchmarks.
> Treat them as *positioning*, not verified performance.

---

## 1. TL;DR

- **Torq is a mature, shipped SOAR/AI-SOC product; autosec's SOC arm is an
  architecturally-correct skeleton with one narrow autonomous lane actually working.**
  Torq: an agentic tier ("Socrates") over a deterministic visual-workflow engine, **150+**
  publicly-enumerable integrations (they claim 300–400), 4,000+ steps, native case
  management, and native MCP. autosec: a real cross-account-AWS-role → deterministic-detect
  → LangGraph-triage → grounded-suggestion loop for **exactly one** finding kind (log-watch
  errors over **self-shipped Docker container logs in S3**, *not* CloudTrail), plus a CSPM
  pillar and a scaffolded second lane.
- **Our structurally different — and defensible — bet: a unified CNAPP data spine
  (normalized Finding SSOT + canonical Asset-URN graph) with the AI-SOC/SOAR as a *consumer*
  of the spine. Torq has no spine — it orchestrates over *other tools'* alerts and natively
  scans nothing.** Caveat: per ADR 0004 the spine is Phase 3a — a write-path-only island
  today (nothing emits `FindingObserved`, nothing subscribes to `FindingRaised`; Prowler
  still writes the legacy `CloudPostureFinding` table).
- **On engineering *discipline* we are genuinely ahead of a typical SOAR:**
  anti-hallucination synthesis, a zero-LLM evidence verifier, per-run cost/blast-radius
  budgets, and a **hard autonomy cap that structurally forbids autonomous irreversible
  actions**. Honest limit: grounding checks a proposed fix against a **single error line's
  own evidence** — no external enrichment yet, so "root-cause context" today is a grounded
  guess from one message, not a corroborated investigation.
- **On *product surface* Torq wins decisively and it isn't close:** no-code visual builder,
  large connector catalog, native MCP (Host + Server), native case management, RBAC/audit
  maturity, MSSP-scale multi-tenancy, and a working IOC-enrichment/threat-intel catalog.
  autosec has ~1 outbound webhook, 3–4 integration surfaces, **no MCP surface at all**, and
  the whole workflow UI is feature-flagged off.
- **Two load-bearing bugs mean our security path likely doesn't fire today** (confirmed from
  code — see §6): (a) `dispatch_event` drops finding events that lack a `target_id`, and the
  real emitter builds a payload without one → the seeded security playbooks never start;
  (b) `run.target` is modeled as a CRM "contact," so action nodes no-op on a security run
  even if dispatch fired.
- **Torq is not without real weaknesses, and they're where autosec can wedge:** **it
  natively scans nothing** (no CSPM/CWPP/CIEM/vuln/asset-discovery — it reacts to Wiz / Prisma
  / Orca / Security Hub findings); its reasoning is bounded by upstream coverage (~70% SIEM
  coverage ⇒ ~70% investigated); no air-gapped mode; enterprise-only economics (~$450K/yr
  reported, procurement in *quarters*); weeks-to-months to production; no published AI
  precision/recall; hard engine ceilings; and an **alpha-versioned (`/v1alpha`)** management
  API with **webhook-only** (not REST) execution.
- **The right roadmap is not "catch Torq on connector count"** — it's: (1) fix the
  dispatch/target correctness gap, (2) make a finding/asset a first-class workflow target,
  (3) wire the Finding SSOT so the spine stops being an island, (4) build a *small, deep*
  IOC-enrichment + threat-intel action catalog on the existing node seam, and (5) pick a
  self-serve/SMB pricing wedge and an MCP-extensibility stance. Do these on existing seams,
  not parallel pipelines.

---

## 2. What Torq is

Torq is an AI-native SOAR / "hyperautomation" platform rebranded to the "AI SOC" category:
a **hybrid** architecture where a deterministic, well-tested visual-workflow engine (300–400
*claimed* prebuilt integrations — **150+** publicly enumerable — 4,000+ pre-built steps,
rule-based dedup/normalize/route) sits *underneath* an agentic reasoning tier called
**Socrates** — an "OmniAgent" that orchestrates specialized parallel HyperAgents
(Enrichment, Investigation, Remediation, Case Management) to run the full triage →
investigation → response lifecycle, *claiming* ~90–95% of Tier-1 cases closed autonomously.

It is deliberately a **stack-agnostic triage/response layer that sits *on top* of the
existing SIEM/EDR/IAM via API** — **not a detection engine, data lake, or CNAPP.** Its
intelligence is bounded by the upstream tools it is wired to (Torq's own framing: ~70% SIEM
coverage ⇒ ~70% of activity investigated). Governance is "human-on-the-loop" via a
confidence-plus-impact escalation model, with native case management as an always-updated
source of truth. **Native MCP (dual-role Host + Server)** is its most-cited recent technical
differentiator.

---

## 3. Where autosec is genuinely better / has a structurally different bet

Honest about *shipped* vs *designed*, these are real:

- **A unified CNAPP finding+asset spine is a fundamentally different — and arguably deeper —
  thesis than SOAR.** Torq orchestrates workflows over *other tools'* alerts and owns no
  unifying finding/asset data model; **it natively scans nothing** and its "Context Graph" is
  a *decision/entity memory* fed by connectors, not a scanned cloud-resource inventory.
  autosec is building the CNAPP core: one normalized Finding (OCSF-aligned,
  `(workspace, source, fingerprint)` dedup identity) plus a canonical Asset graph keyed by a
  shared `AssetUrn` value object, with dedup + steady-state noise suppression *modeled into
  the data layer*. The SOAR/AI-SOC layer is a **spoke-out consumer** of the spine — the
  inverse of a product where automation *is* the product. **Caveat: built to Phase 3a only —
  the SSOT is a write-path-only island (zero producers/subscribers wired), Prowler still
  writes the legacy table, and there is no attack-path correlation (`AttackPathDetected`
  exists as an unused event type).**
- **Agent-native / LangGraph deep-agent design, not chatbot-on-SOAR.** autosec's triage *is*
  a LangGraph orchestrator with a real planner, transient-only worker retries, replan-once,
  reducer-united concurrent-worker cost accounting, and a `publish_event`/`ai` node that lets
  a *playbook* invoke autosec's own deep-agent arm in-process — the CNAPP hook a generic SOAR
  can only reach via an external LLM step.
- **Anti-hallucination and honesty engineering that is incident-driven, not marketing.** The
  synthesizer refuses to narrate a failed/truncated AgentExecutor run as success;
  `verify_suggestion` grounds every proposed fix against the finding's *actual* error
  evidence deterministically (zero-LLM), re-advises once, and downgrades confidence + flags
  `needs_human` if still ungrounded. Honest limit: it grounds against one log line's own
  evidence, not external corroboration (no enrichment yet — see §5/§7).
- **Blast-radius governance is structural, not policy-configured.** Per-run budgets
  (iterations/tasks/wall-clock/failures/**cost-USD**), risk-tiered tools, a platform kill
  switch, and an **autonomy cap that denies autonomous runs any irreversible action**. Torq's
  automations run whatever the playbook says.
- **AWS onboarding is production-grade** (vendor-generated confused-deputy ExternalId,
  least-privilege managed policies, CloudFormation **and** Terraform generation, a
  service-managed StackSet with AutoDeployment so future member accounts self-enroll;
  role-assumption only, customer keys never stored) — deeper than a generic SOAR's "take an
  API key," but it's *one* deep connector, not breadth. **Note:** the connector reads
  self-shipped Docker json-driver logs from S3 — there is **no** SQS consumer, no CloudTrail
  parsing, and the "5 MITRE detections" are not built.
- **Reliability primitives that make "batch but correct" honest:** outbox→Celery dispatch,
  `select_for_update` idempotency, dispatch-after-commit, cache leases, `IngestCheckpoint`
  cursors — versus Torq's elastic-but-vendor-unbenchmarked throughput.

---

## 4. Where Torq is clearly ahead

No spin — this is most of the product surface a buyer evaluates:

- **No-code maturity.** A real visual Builder with autocomplete, tree-mode context
  navigation, and example-output preview. autosec's engine is clean but the *entire end-user
  UI is gated behind `feature.workflows_ui`* — customers can't build or see workflows yet.
- **Integration breadth + MCP.** 300–400 *claimed* integrations (**150+** enumerable) across
  ~22 security categories, an open step model (HTTP-mode, cURL-paste, **Docker container
  steps**, inline Python/JS/PowerShell/Bash), and **native dual-role MCP (Host + Server)**.
  autosec has ~3–4 surfaces total (AWS audit-role, GitHub PAT, Slack sink [model-only, zero
  delivery code], webhook sink [model-only]), **no MCP surface**, and **no connector-registry
  abstraction** — each source/sink is a bespoke Django model.
- **Proven autonomous triage at scale (vendor-cited).** Carvana (100% of Tier-1 + 41 runbooks
  in a month), Valvoline (~7 analyst hrs/day) — *vendor-cited, not neutral benchmarks*.
  autosec's autonomy is real but confined to one finding kind, batch/scheduled (next-tick,
  not event-driven), parallelism 4, no high-volume load testing.
- **Case management** — *ahead on the object, but we are closer than "no model" implies (see
  §4.1).* Torq has a first-class **OCSF-compliant Case object** (typed schema, MITRE ATT&CK
  mapping, SLA timers, AI summary, immutable typed timeline, observable graph). autosec has
  **no incident/Case entity and no correlation/alert-grouping** — every finding is an
  independent Kanban `Task`. **But** that `Task` already carries most of the *substrate*: a
  `Column`/`Status` state machine, `assigned_to`, `Priority`, a `due_date`, an OCSF-aligned
  `Severity` (in `shared_kernel/domain/security`, stored in `metadata`), an **append-only
  `metadata.provenance.events[]` event log**, threaded `TaskComment`s, and grouping containers
  (`Task.project` + `ProjectMilestone`). What's missing is the *correlation logic*, typed
  security fields promoted out of the JSON blob (MITRE doesn't exist yet), and a case-scoped
  typed timeline linking workflow executions — a medium build on existing rails, not a
  greenfield SOC console.
- **Elastic execution.** Cloud-native event-driven engine that absorbs alert storms
  (third-party analysts *cite* ~5x throughput — unbenchmarked). autosec is per-workspace
  batch cadence.
- **Governance / RBAC / MSSP multi-tenancy.** Granular scope-based RBAC, per-case access
  restriction, immutable audit log, Case-Reviewer approval lifecycle, MTTA/MTTI/MTTR + SLA
  dashboards, cross-workspace omni-view built for **MSSP/MDR scale**. autosec reuses
  board/audit/sign-off substrate but is single-tenant-per-workspace batch cadence, with no
  MTTR reporting.
- **Real "response."** Native action library (quarantine email, block domain/URL, reset
  creds, isolate endpoint). **autosec has exactly one real remediation action — open a
  *draft* GitHub PR — which is itself IRREVERSIBLE and therefore denied to autonomous runs.**
  So our "response" is propose-and-comment; humans remediate.

### 4.1 Case management — how close are we, really?

A code review of the Kanban/projects substrate (`infrastructure/persistence/project/models.py`
+ the finding→Task path) shows the "no case management" framing is misleading. **The Case
*object* doesn't exist, but ~70% of the substrate to build one already does** — case
management here is a *medium build on existing rails*, not greenfield.

| Case capability (Torq) | autosec today | Where |
|---|---|---|
| State machine / statuses | ✅ `Column` + `Status` enum | `project/models.py` `Column`, `Task.status` |
| Assignee | ✅ `Task.assigned_to` (M2M) | `project/models.py:232` |
| Priority | ✅ `Priority` enum | `project/models.py:241` |
| SLA | ◑ `Task.due_date` (a due date, **no** SLA timers/pause, no MTTA/MTTI/MTTR) | `project/models.py:239` |
| Severity | ◑ OCSF-aligned `Severity` VO, but stored in `Task.metadata`, not a typed column | `shared_kernel/domain/security`; `specialist_persistence_service.py:167` |
| Timeline | ◑ append-only `metadata.provenance.events[]` + threaded `TaskComment` + immutable `audit` — but not a case-scoped *typed* feed | `specialist_persistence_service.py:154-160`; `project/models.py` `TaskComment` |
| Lifecycle status | ✅ `metadata.triage.status` (pending→triaged) | `specialist_persistence_service.py:176` |
| Grouping container | ◑ `Task.project` FK + `ProjectMilestone` exist, but nothing *populates* them by correlation | `project/models.py` `Project`, `ProjectMilestone` |
| **Correlation / alert-grouping** | ❌ nothing groups related findings into an incident | — |
| **Case/Incident entity** | ❌ no incident entity; no `Task` self-parent FK | — |
| **MITRE ATT&CK mapping** | ❌ no MITRE field anywhere | — |
| **Observable graph** | ❌ = the Finding-SSOT + asset-graph work (items #2/#7) | — |
| **Workflow-execution links on the timeline** | ❌ per-card provenance only, not case↔run links | — |

**The real work is three things, not "build case management":** (1) **correlation logic** that
groups findings into an incident (start `AssetUrn`-keyed — roadmap item #7), reusing
`Task.project`/`ProjectMilestone` or a thin `Incident` entity as the container; (2) **promote
security-typed fields** (severity as a queryable column, add MITRE, observables via the asset
graph) out of the `metadata` JSON; (3) a **case-scoped typed event timeline** that links
workflow executions — generalizing the existing `provenance.events[]` pattern. Sequenced after
the Finding SSOT is wired (item #2), because correlation needs the normalized finding + asset
identity to group on.

---

## 5. The workflow-builder gap, specifically

**Torq's playbook model** (worked phishing/IOC example):
`integration/webhook/email trigger` → `set-variable` / extraction → `Loop (Items)` over IOCs
→ **nested cache-backed enrichment** (VirusTotal, AbuseIPDB, OTX, GreyNoise, URLScan,
sandboxes) → `Collect` verdicts → `If`/`Switch` verdict logic (AND/OR groups) → optional
`Torq Interact` HITL approval → containment/`status` actions → `Exit`. State lives in
workflow/workspace/table variables (4 MB / 50 MB caps); error handling is **per-step** retry
+ backoff (no generic try/catch); modularity via nested workflows with `Exit`-operator
return values. Engine ceilings: 50k sequential steps (10k parallel, 1k Until-Break).

**autosec's model** (`components/workflow/`) is architecturally comparable on *engine
primitives* and in some ways cleaner. We **have**: `start/end`, `condition` (2-way predicate
DSL over dotted-path fields), `switch` (N-way first-match), `wait`/`wait_until` (event-or-
timeout, row-locked), `decision`/`data_request` (HITL pause), `ai` (run a triage agent
inline), `publish_event`, `webhook` (with a real SSRF guard), plus validate/template/
AI-draft/schedule surfaces. The `condition`/`switch`/`wait_until` decisioning is genuinely
autonomous and server-side.

**Concrete building blocks we lack vs Torq's phishing playbook:**

| Torq building block | autosec status | Gap |
|---|---|---|
| **IOC-enrichment steps** (VirusTotal, AbuseIPDB, OTX, GreyNoise, URLScan, sandbox) | **None** | The single biggest workflow-content gap — it's what makes a phishing/IOC playbook *do* anything, and the same missing piece that keeps the deep-agent's "root-cause context" at one-error-message grounding. |
| **Threat-intel integration catalog** | **None** | No TI connectors; no connector registry to hang them on. |
| **`Loop` over a collection** (Items/Range/Until-Break) + `Collect` | **None** | No loop/iterate node — can't fan-out enrichment over an IOC list. |
| **`set-variable` / workflow variables** (workflow/workspace/table) | **None modeled** | Run context carries trigger payload + target + prior step outputs, but no explicit variable get/set/table primitive. |
| **Operator/`Exit` + nested-workflow return values** | **Partial** | No nested/child-workflow operator, no `Exit`-style return; `publish_event` supports exactly one hard-coded event type. |
| **Status/containment response actions** (block IP, isolate host, disable key, quarantine, ticket) | **None** | Action catalog is CRM-shaped (tag a contact, update a UserProfile field, email a contact). |
| **SOC transports** (Slack/Teams/PagerDuty) | **None** | `sms` is an explicit no-op; email goes to a resolved "contact" address, not a SOC channel. Slack sink is model-only. |
| **Native MCP (Host + Server)** | **None** | No MCP surface — can't expose autosec's tools to, or consume, MCP servers. |
| **Per-step retry/backoff config** | **Whole-run only** | Retry resumes at the failed node but there is no per-node retry/backoff policy. |
| **Finding/asset as a run target** | **Broken** | `run.target` resolves to a CRM contact; action nodes no-op on a security run (see §6). |

See `docs/plans/ioc-enrichment-node-and-threat-intel.md` for the build spec that closes the
top three rows on the existing node/detector/registry seam.

---

## 6. The two correctness bugs (confirmed from code)

These mean the security path very likely does not fire end-to-end today. **File before any
workflow demo.**

**Bug 1 — finding events are emitted then dropped for lack of a target.**
- Emitter `_emit_finding_triggers` builds a payload with `task_id`, `severity`, `service`,
  `source_type="finding"` … but **no `target_id`/`target_type`/`contact_id`**
  (`components/agents/application/handlers/specialist_persistence_service.py:234–243`). It
  sets `source_id=task_id` intending "the run targets the finding" (see the comment at
  `:246–247`).
- `dispatch_event` reads the target **only** from
  `payload["target_id"] or payload["contact_id"]`
  (`components/workflow/infrastructure/adapters/dispatcher.py:56`), then for each matching
  binding logs `workflow_event_dropped no_target` and `continue`s when it's absent (`:81–86`).
  The `source_id` the emitter set is never consulted as the target.
- Net: `finding_raised` / `finding_high` / `finding_critical` `WorkflowEvent` rows are
  created, then every run is dropped — the seeded security playbooks appear wired but never
  start.
- **Untested:** `components/agents/tests/integration/test_finding_workflow_emit.py` asserts
  only that `WorkflowEvent` rows exist, never that a `WorkflowRun` is created. The one passing
  dispatch test (`test_dispatch_null_source_binding.py`) hand-injects `target_id="contact-1"`.

**Bug 2 — `run.target` is a CRM contact, not a finding/asset.**
- `components/workflow/infrastructure/adapters/node_actions.py` documents it: `run.target_id`
  is "the contact's user id"; `_resolve_contact_user` returns `None` unless
  `run.target_type ∈ (None,"","contact")` **and** the id parses as a `CustomUser` UUID
  (`:80–101`); `_resolve_membership` resolves the `WorkspaceMembership` (`:104–117`).
- A finding's `task_id` is a `Task` id, not a `CustomUser` id — so even if dispatch fired,
  `message` / `assign` / `add_tag` / `update_field` all resolve to `None` and no-op (or fall
  back to a donor email). There is no notion of a finding/asset/host/identity as a
  first-class run target.

**Root fix (not a bandaid):** teach the run context to resolve a **finding/asset target**
(not inject a fake `target_id`), and give `dispatch_event` a target derived from
`source_id`/`source_type="finding"` when no contact target is present — with an end-to-end
test that drives the *real* `_emit_finding_triggers` payload through to a started `WorkflowRun`
and an executed action node. Tracked as roadmap item #1 (§8) and filed as GitHub issues.

---

## 7. Pricing, GTM, and the strategic wedge

- **Torq is enterprise-only by economics.** Quote-based Professional/Enterprise tiers,
  reported deals ~**$450K/yr**, procurement **in quarters**, weeks-to-months
  time-to-production. A free Community Edition exists as top-of-funnel, but the real product
  lands via enterprise sales.
- **autosec is a SaaS with a baked-in subscription/tiers/entitlements billing stack from day
  one** (Free/Pro/Premium, Stripe, org/team-plan billing). That is a *structural* wedge:
  Torq cannot serve self-serve / SMB / mid-market without re-architecting its GTM. autosec
  can — **if** it ships a usable surface (today it can't; UI is flagged off).
- **The deepest wedge — Torq scans nothing.** Torq's own docs say it "integrates with leading
  CNAPP/CSPM tools … to provide automated triage, prioritization, and remediation." The
  *scanning* is done by Wiz / Prisma / Orca / Lacework / Aqua / Security Hub; Torq orchestrates
  response on *their* findings. **A CNAPP that owns the finding at the source (native scanners
  → unified Finding SSOT → canonical asset graph) doesn't depend on an upstream vendor to
  generate the signal Torq can only react to.** That is the single most important
  differentiation for the roadmap.
- **Founder takeaway:** don't fight Torq at the enterprise SOC where its integration moat and
  case maturity win. Win the segment Torq's price and procurement exclude — self-serve,
  security-conscious SMB/mid-market on AWS — with an honest "detect → grounded-triage →
  propose (human-gated)" loop on a unified CNAPP spine that Torq structurally cannot own.

---

## 8. Prioritized improvement roadmap

Ranked by leverage. Respecting repo rules: **reuse the existing node/detector/router seam
(extend, don't fork); deep fixes not bandaids; route findings through the SSOT; keep the
CNAPP hub-and-spoke shape.**

| # | Item | Why it's highest-leverage | Lives in (context / file) | Tag |
|---|---|---|---|---|
| 1 | **Fix the finding-dispatch drop + make finding/asset a first-class run target.** Stop dropping no-`target_id` finding events; resolve a finding/asset target in the run context; add an end-to-end test using the *real* `_emit_finding_triggers` payload. | The headline security path is scaffolded-not-working. Everything else in workflows is moot until a finding actually starts and drives a run. | `dispatcher.py::dispatch_event`; `node_actions.py` (target resolution); new integration test; producer `specialist_persistence_service.py::_emit_finding_triggers` | reuse-seam |
| 2 | **Wire the Finding SSOT: emit `FindingObserved` from detectors, subscribe `FindingRaised`.** Route Prowler + logwatch through `RecordObservedFindingUseCase` (strangler alongside legacy tables); bind the handler to the bus; add one subscriber. | Turns the CNAPP spine from island into source of truth (ADR-0004 Phase 3b). Unblocks dedup/correlation/attack-path. The hub the whole spoke-out thesis depends on. | `components/findings/`; event bus `SubscriptionRegistry`; producers in `components/agents/.../detectors/` + `components/cloud_posture/` | reuse-seam |
| 3 | **Add an IOC-enrichment node type + a small, real threat-intel connector set (VirusTotal, AbuseIPDB, GreyNoise, OTX).** One new `enrich` node backed by an enrichment **port**; connectors as adapters behind it. | The single biggest *workflow-content* gap vs Torq's phishing playbook, AND the fix that lifts the deep-agent's grounding beyond one error message. Small deep catalog beats chasing 300 integrations. | New node in `components/workflow/domain/constants.py` + executor in `node_actions.py`; connectors under `components/integrations/` behind an enrichment port. See `docs/plans/ioc-enrichment-node-and-threat-intel.md`. | new |
| 4 | **Introduce a connector-registry abstraction (source + sink + enrichment) — and decide whether it speaks MCP.** Generic connector interface + catalog + secret-envelope reuse; evaluate exposing/consuming MCP rather than bespoke adapters. | Directly attacks the defining gap (§4) and the total MCP absence. Without it, every integration is a hand-rolled model+adapter+controller (anti-DRY). Makes items 3, 5, 10 cheap. | `components/integrations/` (new registry/port + provider; MCP stance); reuse `secret_envelope.py` | new |
| 5 | **Ship a first real reversible SOC-response action + a real Slack sink delivery path.** Wire the model-only Slack sink to actual delivery; add one reversible containment action (e.g. block-IP/tag-asset) as a risk-tiered tool. | Moves us from propose-and-comment toward *act*. Reusing the risk-tier + autonomy-cap governance keeps irreversible actions human-gated. | `components/integrations/` (Slack delivery); `node_actions.py` + `components/agents/.../tools/` (action, tagged via `application/policies/tool_risk.py`) | reuse-seam |
| 6 | **Add a `loop`/`collect` node + workflow variables (set/get).** Enables fan-out enrichment over an IOC list and multi-step state — Torq's Loop+Collect+set-variable trio. | Prerequisite for any non-trivial IOC playbook; the enrichment node (item 3) is far weaker without iteration. Pure-domain extension of the graph model. | `components/workflow/domain/constants.py`, `domain/value_objects/workflow_graph.py`, `domain/validators.py`, `node_actions.py` | reuse-seam |
| 7 | **Add finding correlation / alert-grouping (incident) on the existing Kanban substrate — start with `AssetUrn`-keyed grouping.** Group related findings by asset/fingerprint into an incident; reuse `Task.project`/`ProjectMilestone` (or a thin `Incident` entity) as the container, promote severity/MITRE out of `Task.metadata` into typed fields, and generalize `metadata.provenance.events[]` into a case-scoped typed timeline with workflow-execution links. Groundwork for `AttackPathDetected`. | Torq's Case object is a top gap **but we're ~70% of the substrate there** (§4.1) — the missing piece is correlation over the SSOT (a graph query by `AssetUrn`), not a greenfield ticket system. Also our honest answer to alert fatigue. Advances ADR-0004 Phases 5/6. Sequenced after item #2 (needs normalized finding + asset identity to group on). | `components/findings/` (correlation domain service + read model) consuming shared-kernel `AssetUrn` + `AttackPathDetected`; container/timeline on `infrastructure/persistence/project/` (`Task`/`Project`/`TaskComment`) | reuse-seam |
| 8 | **Turn on a minimal read/query + UI surface for findings and workflows (behind the flag).** Add the missing `api/controller.py`/`urls.py`/CQRS query to findings; plan a phased un-freeze of `feature.workflows_ui`. | The spine and engine are invisible to customers today (write-path-only findings, UI flagged off). Even internal demo value needs a read surface. Sequenced after 1–2. | `components/findings/api/`; `components/workflow/api/controller.py` (flag policy) | reuse-seam |
| 9 | **Add per-node retry/backoff policy config + honest failure surfacing in the run timeline.** Extend the retry-from-failed-node model with per-node attempts/delay/backoff. | Reliability parity with Torq's per-step retry; small, high-confidence extension of an already-correct (idempotent, row-locked) engine. | `components/workflow/domain/constants.py` (node config), `infrastructure/tasks/workflow_tasks.py` | reuse-seam |
| 10 | **Broaden inbound ingestion beyond AWS-S3 logs (Slack/Sentry/CloudWatch webhook-in) via the item-4 registry.** A webhook-in trigger framework feeding the detector cycle. | Closes the credibility gap between the CLAUDE.md pitch ("routes Slack/Sentry/CloudWatch alerts") and reality (self-shipped-Docker-logs-in-S3-only, no SQS consumer). Do it on the registry seam. | `components/integrations/` (webhook-in trigger); `components/agents/application/services/detector_cycle.py` | new |

**Framing for the founder:** don't out-integration Torq — that's their moat and a years-long
slog. Win where the *architecture* and the *GTM model* already bet differently: fix the two
correctness bugs so our one real autonomous lane demonstrably works end-to-end, wire the
Finding SSOT so the CNAPP spine is real, build a *small deep* enrich+respond catalog on
existing seams, and aim it at the self-serve/SMB segment Torq's ~$450K/quarters-procurement
model structurally can't serve. That yields a working, honest "detect → correlate →
grounded-triage → enrich → act (human-gated)" loop on a unified CNAPP data model — a story
Torq structurally cannot tell, because it has no spine of its own.

---

## Appendix A — Torq mechanism reference (URL-cited)

*Grounded in Torq's public KB, developer docs, and product/blog pages, mined July 2026.
Marketing efficacy numbers flagged as such.*

### A.1 Workflow-builder primitives
Visual canvas; every workflow is `trigger → steps/operators → accumulating JSON context`,
serialized as JSON.

- **Trigger types** ([Workflow Triggers](https://kb.torq.io/en/articles/9121101-workflow-triggers-in-torq-initiating-workflow-executions)):
  **On-Demand** (manual; callable as nested workflow or exposed as a Socrates/AI-agent tool;
  typed inputs read as `$.event.<param>` — [On-Demand](https://kb.torq.io/en/articles/9112879-on-demand-triggers-enable-user-initiated-executions)),
  **Integration** (third-party webhooks incl. a Generic Webhook — [Integration Triggers](https://kb.torq.io/en/articles/9130865-integration-triggers-in-torq-ingest-data)),
  **Schedule** (cron), **System Events** (workflow/step failure, review requests — the
  escalation seam — [System Events](https://kb.torq.io/en/articles/9128772-trigger-workflows-with-torq-system-events)),
  **Torq Cases** ([Cases Triggers](https://kb.torq.io/en/articles/9138475-cases-triggers-initiate-workflows-with-torq-case-management-events)),
  **Torq Interact** (human-input web forms), **Email** (unique `@mg.torq.io` address; subject/
  body/headers/attachments; 4 MB cap — [Email Trigger](https://kb.torq.io/en/articles/11560283-email-trigger)).
- **Step/action model** ([Explore Steps](https://kb.torq.io/en/articles/9122841-explore-torq-steps-workflow-building-blocks)):
  step = one action; categories Integration / HTTP / Utility / Custom / Operator; steps
  connect sequentially, parallel branches by dragging one step onto another; per-step
  Execution Options (runner choice, retry, data-retention, output format).
- **Operators / conditional logic** ([Operators](https://kb.torq.io/en/articles/9121891-operators-in-torq-workflow-flow-control),
  [Conditions](https://kb.torq.io/en/articles/9110256-understanding-conditions-in-torq-workflows)):
  **If**, **Switch** (left-to-right priority), **Loop**, **Wait** (status→On-hold), **Parallel**.
  Comparators: eq / ne (case-insensitive), in / not-in, contains / not-contains
  (case-sensitive), >, <, >=, <=, regex match / not-match, is-empty / not-empty; grouped with
  AND/OR; data via `$.` JSONPath. (Literal `["A","B"]` parses as a *string* — arrays must go
  through JSON variables.)
- **Loops** ([Loop Operator](https://kb.torq.io/en/articles/9144380-loop-operator-automate-iterative-processes-with-torq)):
  **Items / Range / Until-Break**; Sequential (default) vs Parallel (**batches ≤10**;
  incompatible with Until-Break); `{{ $.loop_index }}` / `{{ $.loop_value }}`; **Collect**
  aggregates per-iteration output; **Break** exits. Caps: sequential 50,000, parallel 10,000,
  Until-Break 1,000.
- **Variables & data types** ([Workflow Context](https://kb.torq.io/en/articles/9175119-workflow-context-understand-data-access-and-utilization-in-torq),
  [Workspace Variables](https://kb.torq.io/en/articles/9202852-workspace-variables-in-torq-optimal-data-management)):
  all data JSON; JSONPath (`$.event`, `$.<step>`, `$.integrations`, `$.secrets`) + template
  (`{{ $.event.user.firstName }}`); types Text/JSON/Boolean/Number/Table; sizes standard 4 MB,
  **Table 50 MB**; scopes workflow / workspace-global / system; formulas via **govaluate**.
- **Nested / sub-workflows** ([Nested Workflows](https://kb.torq.io/en/articles/9139661-nested-workflows-in-torq-improve-modularity-and-reusability)):
  parent calls child via **Workflow operator**; child needs On-Demand trigger + **Exit
  operator** (outputs read as `{{ $.<nested>.<field> }}`); controls **Ignore failure**,
  **Wait for output** (unset = fire-and-forget parallel).
- **Error handling** ([Auto-Retry](https://kb.torq.io/en/articles/9112337-set-steps-to-automatically-retry-enhancing-workflow-reliability-in-torq)):
  **no generic try/catch**; per-step Retry-after-failure / Retry-on-condition; exponential
  backoff (default 1.25×); retries persist up to **31 days**; on-hold time **does not consume
  execution quota**; **Ignore failure** decides fail-vs-continue; workspace-wide handling via
  System Events triggers.
- **Phishing / IOC-enrichment pattern** (shipped templates): trigger → extract IOCs/URLs from
  `$.event` → **Loop (Items)** → nested cache-backed enrichment
  ([VirusTotal URL Enrichment w/ Cache](https://kb.torq.io/en/articles/9350235-workflow-template-virustotal-url-enrichment-with-cache),
  [URLScan scan + summary](https://kb.torq.io/en/articles/9350271-workflow-template-scan-urls-with-urlscan-and-provide-a-summary),
  [VT IOC 6-hour cache](https://kb.torq.io/en/articles/9350090-cache-virustotal-threat-intelligence-findings-on-an-ioc-workflow-template))
  → **Collect** → **If/Switch** on verdict → contain/escalate or close.

### A.2 Auto Triage
- **3 verdicts** (`True Positive – Malicious`, `True Positive – Benign`, `False Positive`) ×
  **5 severities** (Critical/High/Medium/Low/Informational); each alert also gets reasoning,
  **MITRE ATT&CK mapping**, recommended actions
  ([verdicts KB](https://kb.torq.io/en/articles/13673175-how-torq-s-auto-triage-determines-alert-severity-and-verdicts),
  [auto-triage](https://torq.io/auto-triage/)).
- **Verdict drivers:** observable reputation (hash/IP/domain, seen-before-in-env) + kill-chain
  alignment + **historical closed-case matching** (search account's closed cases by
  observable) + threat intel (commercial e.g. ReversingLabs + OSINT) + business context
  (VIPs, crown jewels) + analyst feedback loop. Pipeline: connectors → **normalize to OCSF**
  → auto-extract observables → enrich → agentic reasoning.
- **Two customization knobs:** **Guidance** (soft, AI-weighted signals) vs **Rules**
  (deterministic hard-set severity/verdict).
- **HITL:** three lanes — fully automated / escalate to human / close with evidence
  ([SOC triage use case](https://kb.torq.io/en/articles/12094965-use-case-automate-soc-triage-with-ai-agents));
  a documented **End User Interviewer** agent DMs the affected user on Slack to gather context
  before verdict. Bidirectional with workflows (TP → Case; verdicts produced *by* workflow-
  invoked agent chains).

### A.3 Case management (Investigate Cases / HyperSOC)
- **OCSF-compliant Case object** ([enterprise case mgmt](https://torq.io/blog/torq-enterprise-case-management/)):
  metadata/taxonomy (type/source/severity/MITRE/SLA), **observables graph**, dynamic parallel
  enrichment, AI triage (Socrates, RL from resolved cases), risk-gated execution. Elements:
  assignees, SLA, tasks, custom states/fields/tabs, notes, attachments, linked related cases,
  events, observables, runbooks ([Cases](https://kb.torq.io/en/collections/8856042-cases)).
- **Observables = evidence spine** ([Observables](https://kb.torq.io/en/articles/9202637-observables-enhance-threat-detection-with-torq)):
  persist in DB independent of any case, link to many cases, "Cases with this Observable"
  table, shared enrichment JSON, full audit history; one can be **Key Observable**.
- **Timeline** ([Case Timelines](https://kb.torq.io/en/articles/9167040-case-timelines-in-torq-track-investigation-progress)):
  chronological comments + events, **24 event types**; workflow-initiated entries **link to
  the execution** (case↔workflow traceability); every field mod versioned; immutable trail.
- **Analyst console = Socrates** ([Socrates](https://kb.torq.io/en/articles/9734818-socrates-ai-analyst-transform-case-investigations)):
  conversational or **assign the case directly to Socrates** (acts as analyst, follows the
  runbook); custom workflows exposed to it **as tools**; one-click isolate/revoke/block behind
  **deterministic approval gates**.
- **Metrics** ([Cases Dashboards](https://kb.torq.io/en/articles/10342755-cases-dashboards-monitor-hypersoc-metrics),
  [SOC posture template](https://kb.torq.io/en/articles/10146109-cases-dashboards-template-soc-posture)):
  **MTTR / MTTA / MTTI**, Created Cases; **Insights Dashboard** tracks **Time Saved** via
  per-workflow "TimeBack" benchmarks
  ([Insights](https://kb.torq.io/en/articles/9113853-insights-dashboard-track-time-saved-with-torq));
  PDF export; Private / selected / all visibility.

### A.4 AI / agentic SOC (Socrates)
- **Multi-Agent System** ([MAS](https://torq.io/blog/the-multi-agent-system-a-new-era-for-secops/),
  [HyperSOC-2o](https://torq.io/blog/hypersoc-2o/)): **Socrates (OmniAgent)** orchestrates
  four micro-agents — **Runbook** (NL→workflows), **Investigation** (logs/TI/CMDB/identity,
  root-cause, attack paths), **Remediation** (isolate/revoke/firewall — autonomously or
  escalate), **Case Management** — which call **HyperAgents** (task workers). Underlying
  foundation model / agent framework is **never disclosed** (a transparency gap to probe).
- **Memory / learning (strongest technical area)** — **Context Graph + three-layer memory**
  ([Context Graph & Memory](https://torq.io/context-graph-and-memory/)): **semantic** (entity
  graph from IdP/EDR/SIEM/cloud/HR/ITSM/TI; decisions are first-class objects; contextual
  entity resolution), **episodic** ("Torq Recall" — retrieve prior cases sharing entities),
  **procedural** ("Torq Reflex" — a **per-tenant ML model trained continuously on
  analyst-confirmed verdicts**). RAG: fast retrieval → AI re-rank by entity overlap →
  grounded verdict citing precedents. *This maps closely onto autosec's finding-SSOT +
  asset-graph + agent-memory direction — it validates our thesis.*
- **Autonomy** — human-on-the-loop; Remediation "operates independently"; agents run in
  parallel, share context, adapt mid-session. Efficacy claims are **marketing (unsubstantiated):**
  "90% of Tier-1 tickets," "95% of Tier-1 alerts," HyperSOC-2o "95% of manual
  triage/investigation" ([Socrates](https://torq.io/news/socrates/), [HyperSOC-2o](https://torq.io/blog/hypersoc-2o/)).
- **Guardrails (well-documented)** ([Guardrails](https://torq.io/blog/agentic-ai-security-guardrails/),
  [AI autonomy](https://torq.io/blog/ai-autonomy-in-the-soc/)): human-in vs on-loop;
  **confidence-threshold routing** (high→auto-quarantine, medium→review-with-investigation,
  low→escalate-with-evidence) with **operator-adjustable, non-hardcoded thresholds**;
  approval gates on high-impact accounts; scope boundaries enforced architecturally;
  uncertainty→human; atomic-task execution; per-decision audit log.

### A.5 Integration & extensibility + REST API
- **Integrations/steps:** KB states **"150+ integrations"** ([Integrate Everything](https://kb.torq.io/en/collections/8617357-integrate-everything));
  marketing inflates to "200+/250+ vendors" — cite **150+** as conservative. Auth: API keys,
  OAuth 2.0, webhooks.
- **Custom steps:** **Step Builder** from HTTP / cURL / nested workflow (+ "Generate HTTP
  Request with AI" — [Custom Steps](https://kb.torq.io/en/articles/9183207-creating-custom-steps-in-torq-automate-anything));
  any integration step toggles to raw HTTP mode; **full custom code via Docker container
  steps** (any language, image on Docker Hub, env-var inputs, JSON output, `linux/amd64` —
  [Container Step](https://kb.torq.io/en/articles/9024698-build-a-custom-container-step)).
- **MCP — YES, bidirectional (differentiator)** ([MCP](https://torq.io/blog/model-context-protocol/)):
  Torq as **Host/Client** (agents discover + invoke vendor MCP tools — [AI Tools](https://kb.torq.io/en/articles/12065486-ai-tools-enhance-ai-agent-capabilities))
  and as **Server** (its workflows/steps usable as tools inside other hosts, e.g. Claude
  Desktop, IDEs).
- **Developer REST API** ([overview](https://developers.torq.io/apidocs/overview),
  [auth](https://developers.torq.io/apidocs/authentication)):
  - Auth: API key = `client_id` + `client_secret` (UI-created; secret shown once;
    **workspace-scoped**; Service keys need Owner role). OAuth2 **client_credentials** → POST
    `https://auth.torq.io/v1/auth/token` → bearer valid **1 hour**.
  - **Rate limit: 50 req/s.** Timestamps RFC 3339.
  - **Base path `/v1alpha`** on `api.torq.io` / `api.eu.torq.io` — *still alpha-versioned, a
    maturity signal.* Resource groups: Workflows, Executions, Cases, Secrets, Users,
    Workspaces, API Keys, Audit Logs, Integrations, Global Variables, Interactions. Confirmed:
    `POST /v1alpha/workflows` (list), `GET /v1alpha/executions/{id}` (status ∈
    SUCCESS/FAILED/RUNNING/STOPPED/ON_HOLD/QUEUED/DROPPED), `POST /v1alpha/cases/query`,
    create/retrieve case, secrets list/create, api-keys list, audit-logs list,
    `POST /v1alpha/workspaces`.
  - **Triggering a workflow is NOT a REST POST** — it's a **per-workflow webhook URL**
    ([Sync/Async](https://kb.torq.io/en/articles/9140015-trigger-a-workflow-with-an-integration-trigger-sync-async-options)):
    **Async URL** (returns `{"execution_id","status":"ok"}` → poll executions) or **Sync URL**
    (returns output, blocks ≤50 s). The `/v1alpha` API is management/read; execution is
    webhook-driven.

### A.6 Templates
- **~445 workflow-template articles** ([Templates](https://kb.torq.io/en/collections/9398821-templates)),
  tiered Basic/Intermediate. Categories: Threat Intel & Enrichment (VirusTotal, Recorded
  Future, AlienVault, URLScan), Endpoint/EDR (CrowdStrike, Defender, SentinelOne), IAM (Okta,
  Entra ID, JumpCloud), Case Management, Cloud Security (AWS/Azure/GCP), SIEM/Logging (Splunk,
  Sumo, Chronicle, Elastic), IR, Data Protection, Compliance (MITRE/NIST/SOC 2), Communication.
- **Reuse model** ([Templates KB](https://kb.torq.io/en/articles/9297096-accelerate-security-automation-with-torq-templates)):
  Build > Templates > **Import** → setup wizard collects inputs → ready to run; portability
  via workspace import/export (carries embedded custom steps/integrations).

### A.7 Recent trajectory (2026 product updates)
From [torq.io/product-updates](https://torq.io/product-updates/): heavy 2026 investment in
**case management + RBAC governance** (MITRE mapping in cases, security-context case fields,
team/group-based case assignment, **org-managed roles across workspaces**, org viewer role,
cross-workspace dashboards); **Socrates "Step Tools"** (Apr 2026 — the AI agent can call
**workflow steps as tools**, converging agent + no-code worlds — the same bet as our `ai`
node); **native endpoint connectors** (SentinelOne, MS Defender) feeding Auto-Triage with
backfill/filtering; **Step Runners** (K8s/Docker/Podman, non-root, custom labels) for
isolated elastic execution. Their center of gravity is the **case/console/governance** layer
— which maps directly to autosec's most-exposed roadmap items #7 and #8.

### A.8 Concrete Torq gaps/limits (vs a CNAPP that also does posture + findings)
1. **No native scanning of anything** — no CSPM/CWPP/CIEM/vuln/asset-discovery; it reacts to
   third-party scanner findings ([cloud misconfig use case](https://torq.io/use-case/cloud-misconfiguration-detection-remediation/)).
2. **No native asset/posture inventory or attack-path graph** — asset context comes from
   integrating CMDBs/scanners ([vuln prioritization](https://torq.io/blog/vulnerability-prioritization/)).
3. **Reactive, alert-centric data model** — the unit of work is an alert/observable/case, not
   a finding tied to a scanned resource with posture state; no continuous posture drift, no
   compliance-framework state per asset, no IaC-to-runtime lineage.
4. **REST API is management-only and alpha-versioned** (`/v1alpha`); webhook-only execution.
5. **Fixed coarse verdict/severity taxonomy** (3×5) — thin for posture/compliance findings
   needing control-mapping, exception state, blast-radius, asset-scoped risk scoring.
6. **No try/catch in the workflow engine** — per-step retry + Ignore-failure + System Events only.
7. **Efficacy claims unsubstantiated**; underlying LLM / agent framework undisclosed.
