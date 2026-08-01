# State of Auto-Sec + Product Vision

> **Status:** Draft v1 (living document) · **Date:** 2026-07-31
> **Basis:** A full codebase audit (6 parallel subsystem deep-dives across `auto-sec-api` +
> `auto-sec-frontend`) cross-checked against the code, plus 2025/26 market research. Honest about
> **real vs. partial vs. vision** throughout — this feeds product decisions and user research, so it
> deliberately does not oversell.
>
> This is a snapshot; it will drift from the code. Re-ground before building on any specific claim.

---

## 0. TL;DR

Auto-Sec is an **AI-native cloud security platform** built on one idea: **a single security graph, read
through three lenses — defend (blue) / attack (red) / comply (compliance) — with an AI agent arm that does
the SOC *and* the audit-evidence toil.** Under the hood
it's a well-architected CNAPP spine (unified Findings SSOT + cloud asset graph + attack paths) with a
**LangGraph deep-agent orchestrator routing to 13 live specialist agents**, a **multi-source
observability pipeline** with SIEM-grade log detection, and a **reversible response framework**. The
platform foundation (auth, multi-tenancy, SOC-tuned RBAC, billing, flags, audit) is mature and
production-grade.

It sits at the **convergence of three markets that are actively merging** — CNAPP, CTEM / Exposure
Management, and the brand-new Agentic AI SOC category — and its **wedge is real: it's the AI SOC analyst
that _owns the cloud graph_.** Wiz/Orca have the graph but no analyst; Dropzone/Prophet have the analyst
but no graph. Auto-Sec has both.

The honest gaps: the CNAPP engine is **flag-gated dark by default** (per-workspace opt-in — though the
demo workspace already has cloud-posture + asset-graph un-darkened on real data), ATT&CK / compliance
tagging is **Prowler-only** (logs + containers untagged), the **red-team lens is cosmetic**, and there is
**no runtime visibility** (which Gartner now calls table-stakes). _(The hardcoded HUD demo cards were
removed in FE #114 — see §4.)_

---

## 1. The thesis: one graph, three lenses, an agent arm

Everything feeds **one model**:

- **Findings SSOT** (`components/findings`) — the single canonical finding store. Every scanner emits a
  `FindingObserved` event; the findings context owns persistence, dedups on
  `(workspace, source, fingerprint)`, runs the lifecycle (`OPEN → TRIAGED → RESOLVED/SUPPRESSED`), and
  correlates across pillars by `asset_urn`.
- **Asset graph** (`components/cloud_graph`) — typed `CloudAsset` nodes + `CloudAssetEdge` relations
  (`CAN_ASSUME`, `HAS_POLICY`, `ROUTES_TO_IGW`, `READS_BUCKET`, …), with `PUBLIC/INTERNAL/PRIVATE`
  exposure, in Postgres (no graph DB; bounded BFS in a domain service).

Three lenses read it:

- 🛡️ **Blue (defender):** CNAPP posture + observability context + response → *"what's wrong, how bad, and
  the context to fix it."*
- ⚔️ **Red (attacker):** MITRE ATT&CK kill-chain + attack paths over the *same* findings → *"how do these
  chain into a breach?"*
- 🟢 **Comply (compliance):** the *same* findings + asset/access graph, mapped to framework controls and
  packaged as **audit-grade evidence with provenance** → *"show an auditor — with where/when/how each piece
  of evidence was generated — that we're secure."* (New third lens — see ADR 0009 and §2.2.)

The lens is chosen in the HUD via a **"Teams" selector** (a lunar callout listing Defend / Attack / Comply,
+ "Add team") — the old blue⇄red toggle generalized to N teams.

And an **AI agent arm** closes the loop on all three: detect → triage → propose fix → (human approves) →
execute → rollback for blue/red, and control → evidence → chase-and-collect → assemble for compliance.

---

## 2. Market context (grounded)

Three markets are **converging into one**, and Auto-Sec is natively at the center:

- **CNAPP** — Gartner 2025's defining differentiator is now **graph + attack-path correlation**. The 2025
  headline is "**runtime visibility is no longer optional**" — a real gap for us.
- **CTEM / Exposure Management** — VM, ASM, CAASM, ASPM, **BAS**, CTEM and CNAPP are **merging into
  unified "Risk & Exposure Management" platforms** on attack-path prioritization. Our graph + attack
  paths + exposure model *is* this.
- **Agentic AI SOC** — named by Gartner for the first time in 2025; **1–5% enterprise penetration**, with
  ~60% of SOC work expected to shift to AI. Funded leaders (Dropzone $37M, Prophet $30M, CrowdStrike
  Charlotte, MS Security Copilot) triage/investigate/respond — **but none own a CNAPP graph.**
- **Observability + security are converging**; OTel is the unified-telemetry standard
  (logs / metrics / traces). The OBSERVABILITY-pane direction is directly on-trend.

**The wedge:** *the AI SOC analyst whose reasoning is grounded in a real cloud graph* — packaged as
**"the security team you don't have to hire": a fleet of agents standing in for the infosec team a
fast-shipping, AI-native team can't afford and doesn't want to staff.** Differentiated from both
incumbents (CNAPP-without-analyst) and startups (analyst-without-graph). See §2.1 for the operator-founder
signal behind this framing, and [§10 Sources](#10-sources).

### 2.1 First operator-founder signal (Tom, 2026-07-31)

First real feedback session with a target operator: a technical founder (ex-Clio; ~15 years building AI
eval/test suites; revived and recapitalized his own SaaS; ships daily with Claude Code). Close to ICP
*and* deeply technical, so the signal is high-quality. Grounded takeaways:

**The positioning reframe (his words).** *"You're essentially selling an infosec professional team to
people that can't — or don't want to — have a whole one,"* plus *"code is not the problem now; it's **how
do I know I'm shipping safely and at scale**."* This sharpens the ICP from "cloud-native SMB on AWS" to
**AI-era builders / small teams shipping fast with AI-generated code, no security team, no budget for
experts** — the security team you don't hire.

**Double down (explicitly validated — treat as committed direction):**
- **Single pane of glass / cockpit** — "stay in one place, never leave." The whole IA thesis, endorsed.
- **Rearrangeable panels + role-based default templates (operator / red / blue) + saved custom views** —
  strongly validated, and a personal scar for him ("people have role preferences about what's important;
  can you change the ordering/view"). Action: make **saved views first-class and *persisted* per user**,
  with role-preset templates.
- **Per-workspace branding** — "people care about that logo." (Already shipped — keep.)
- **Preventive posture** — "tighten yourself up *before* things get serious / before the bad guys get
  in." Reinforces the CTEM/exposure lean.

**Top validated build gaps (ranked by signal):**
1. **Remediation → draft PR to the linked repo (any fix, any provider).** Unprompted: "that should be a
   feature." Turns out this is *mostly built* — a `GitHubPrPort` + adapter + `OpenDraftPrUseCase` +
   `GitHubConnection` (repo-allowlist, encrypted PAT) + a real triage-agent tool already open draft PRs.
   The gap is **productizing + generalizing** it: no CRUD API / Settings UI to link repos (so GitHub isn't
   in the Integrations UI), and it's GitHub-only. **ADR 0010** generalizes it into a multi-provider
   `VcsPort` (GitHub/GitLab/Bitbucket, mirroring the log-source multiport) + CRUD + panel. Not IaC-specific
   — commits one file + opens a draft PR for *any* fix.
2. **AI-introduced-vulnerability detection** — he lived it: a coding agent shipped broken tenant
   isolation (cross-customer data access). New threat class we're uniquely placed for: *catch the
   security regressions your coding agent introduces* (tenant leaks, secrets, over-permissive IaC in a PR).
3. **Monitoring blind-spot advisor** — his DB fell over because they alerted on CPU/RAM, not disk IO;
   "we weren't monitoring the right thing until we had the problem." Proactively flag *missing* coverage.
4. **Right-remediation advice** — on a bot-scanner flood he first blocked User-Agents (a mistake: UAs
   spoof) before switching to path/WAF blocking. Advisors should encode the *correct* control + reasoning.
5. **LLM / agent-trace observability in the HUD** — his home turf; eval the whole agent *trace*, replay
   provenance if something escapes the sandbox. Fits the OBSERVABILITY pane (an AI/agent tab); we already
   use Langfuse. He cross-referenced Datadog LLM Observability + Langfuse.
6. **Datadog / Splunk log sources + cross-source correlation** — he correlates Datadog + Slack + app +
   traces by hand. Validates prioritizing the Datadog `LogSourcePort` adapter (ADR 0008, Phase 5).

**Meta / founder advice heeded:** don't overbuild — validate with a manual/faked one-off in front of
customers *before* building; trust agent output via golden-dataset eval + confidence values. Direct
implication: **run more operator calls like this before building further.** He offered to test when ready.

### 2.2 Second operator signal — the compliance lens (Andrea, 2026-07-31)

Second feedback session, a *different persona*: a solo security engineer (ex-Clio) who is also the de-facto
compliance owner at a small, cost-cutting startup, mid-flight on a **SOC 2 Type II** with **Vanta**. His
entire world is **audit evidence + the GRC cycle**, not detection — and it reveals a **third co-equal lens
on the same graph: _comply_ (compliance).** This is now a first-class direction (see ADR 0009 for the build).

**The core insight — provenance is the product.** *"You gotta look at a piece of evidence — where it comes
from, how it was made, when it was made, and if it's the original report. That's what gives it credence."*
A raw scan report is worthless to an auditor; the same report **stamped with generation-time, scope,
parameters, source-system, filters, and original-vs-derived lineage** is audit-grade evidence. Auto-Sec's
unfair advantage: **Vanta collects evidence _from_ other tools (weak provenance); Auto-Sec _generates_ the
scans itself, so it can stamp perfect provenance at the source.**

**The second persona.** Overlaps Tom's "no budget for a team," but the felt pain is **audit/evidence**, not
shipping-safely: a solo operator running the audit off a spreadsheet of controls, chasing every team for
screenshots. ICP-adjacent and real.

**Ranked build gaps (→ ADR 0009):**
1. **Audit-grade evidence export with provenance** — every scan/finding/report carries when/scope/params/
   source/filters/lineage, exportable as an auditor-acceptable artifact. (We have the immutable audit trail
   + findings SSOT — gap is *packaging as evidence*.)
2. **Control → evidence mapping + continuous collection** — map automatable evidence (posture, asset
   inventory, access graph, config) to framework controls; auto-collect the API-able, flag the manual. He
   was explicit on the split: **API-able → automate; no-API → manual screenshot; Type II random sampling →
   always manual.** Don't over-promise full automation.
3. **Access inventory / "who can touch what"** — he said it's *not set up and expensive*. That's literally
   `feature.provenance_graph` (dark). Un-dark + package as access-review evidence.
4. **Shadow-AI monitoring + AI-governance evidence** — *"show how many users talk to known AI platforms —
   bonus if you can enforce."* We have the `ai-governance` specialist; gap is a shadow-AI monitor + evidence.
5. **Audit-cycle workflow (kill the spreadsheet)** — assign controls to owners, Slack kickoff, **per-control
   instructions** (owners don't know what a control means practically), over-share context. We have
   workflow + Slack + sign-off; gap is the GRC-cycle orchestration on top.
6. **Cross-source corroboration** — his MDM-list × antivirus-console trick (one report proves inventory *and*
   AV coverage): corroborate two sources for stronger, dual-purpose evidence.
7. **Compliance Q&A + policy drafting** — a recurring ask on his plate: a manager wants a policy *drafted*,
   or wants infra/security questions answered ("do we encrypt files at rest? do we run vulnerability
   scanners? data residency? tenancy?") — the security-questionnaire / org-FAQ grind, today a hand-built
   spreadsheet. An agent grounded in the live graph + findings + config answers these *and* drafts policies,
   with the answer/policy itself emitted as provenance-stamped evidence. Reuses the existing agentic RAG.

**Cautions (his words).** Crowded, sales-heavy market (Vanta even supplies the auditor), and the money quote:
*"Vanta helps you the first time; after that, why do you even need a platform?"* — our own company rolled its
own for the same reason. So the wedge here is **not another onboarding wizard**; it's **automation +
provenance for teams doing it the 2nd+ time**, where owning the source graph is the unfair advantage.

---

## 3. The architecture (why this compounds)

Explicit Architecture (DDD + Hexagonal + Onion + Clean + CQRS), **hub-and-spoke**: many scanners/sources
feed one Findings SSOT + one asset graph (OCSF-normalized); many lenses read it. The load-bearing seams
are all **ports with pluggable adapters**:

- `ScannerPort` + `ScanExecutionBackend` — Prowler and Trivy run as hardened, gVisor-isolated ephemeral
  Kubernetes Jobs (or a local subprocess in dev).
- `LogSourcePort` — S3/CloudTrail + CloudWatch adapters behind a per-workspace `WorkspaceLogSource`
  registry (ADR 0008).
- The deep-agent framework — `@register_agent` auto-discovered specialists behind one orchestrator.

**Consequence:** every new scanner, log source, or agent is *an adapter + a registry line*, never a new
silo. This is the "reproducible arm" property that makes the Kali-for-SOC vision tractable.

Key ADRs: `0004` (CNAPP unified Finding + Asset spine), `0005` (boto3 inventory over CloudQuery), `0006`
(scanner execution substrate), `0007` (red/blue as real teams), `0008` (multi-source log ingestion).

---

## 4. State of the product — layer by layer

### 4.1 Platform foundation — **mature** ✅

Multi-method auth (email/password, Google OAuth, magic link, TOTP/2FA, JWT, geo-aware sessions, support
impersonation); isolated multi-tenancy; **RBAC already SOC-retuned** (`view_findings / manage_detections /
view_cases / run_playbooks / view_agents / manage_assets / view_audit`); clean role-vs-persona split
(ADR 0002); freemium tiers (Free/Pro/Premium) + Stripe Connect; hierarchical feature flags; immutable
audit trail; two-stage recycle bin; per-workspace branding. **`Team.kind = blue_team | red_team` is a
real backend concept** (ADR 0007). Nonprofit-fork drift (donations/grants/marketplace) is isolated,
dormant scaffold — not an active liability.

### 4.2 CNAPP engine — **built, mostly dark** 🟡

- **Scanners:** Prowler (CSPM) + Trivy (container SCA), both real, behind `ScannerPort` /
  `ScanExecutionBackend`. **Flag-gated OFF in prod.**
- **Asset inventory (boto3):** EC2, IAM, S3, DynamoDB, network topology (SGs/subnets/route-tables/IGWs),
  Lambda (minimal). **Gaps:** ECS/Fargate, RDS/Redshift, VPC-peering, cross-account, bucket policies,
  multi-cloud (GCP/Azure).
- **Attack paths:** BFS (depth 6), toxic-combo scoring 0–100, background-materialized, emitted as
  findings — but **flag-gated and not fully UI-wired**, and the findings-emission slice is deferred.
- **Sharp edges:** Prowler's full-account output can exceed the K8s pod-log ~10MB cap → silent
  truncation; no container-image → asset link-back yet.

### 4.3 Findings + MITRE ATT&CK + compliance — **SSOT solid, tagging partial** 🟡

- **SSOT:** real, owner-persists, dedup, lifecycle, `asset_urn` correlation, board `Task` as an
  event-synced local copy. Production-grade.
- **MITRE ATT&CK is built** (tactic catalog with kill-chain order → technique-tagged findings →
  materialized `WorkspaceAttckCoverage` heatmap → the ATTACK COVERAGE HUD card). **But tagging is
  partial:** only **Prowler + attack-path** findings are tagged; **Trivy (containers) and logwatch (logs)
  get no techniques**, and the catalog is only **5 techniques** (more are emitted but silently dropped).
  *This is precisely the "notes don't cite ATT&CK" gap.*
- **Compliance:** Prowler-only, 9 frameworks (CIS/PCI/SOC2/ISO/NIST/HIPAA/GDPR/FedRAMP/AWS-FSBP),
  failing-controls-only (no fabricated %). Aggregation, no compute engine.
- **No contextual-risk scoring yet** (ADR 0004 Phase 6).

### 4.4 Observability — **richer than expected, under-surfaced** 🟡

- **Logs:** multi-source (S3/CloudTrail + CloudWatch) behind `LogSourcePort`; **SIEM-grade deterministic
  detection** — 8 signal types incl. **SQLi signatures, recon/scanner probes, HTTP 4xx/5xx, auth
  failures** — with spike/trend analysis + top-source-IP ranking. Hard rule: never run an LLM over the
  raw firehose.
- **Metrics:** real hourly security-metric buckets + a query service — **but not exposed in the REST
  API** (only reachable through the log-analytics agent). The OBSERVABILITY "Metrics" tab needs a small
  endpoint.
- **Traces:** **none for customer workloads** (Langfuse traces *our own agents* — a different concern).
  This is the net-new pillar.
- **Threat-intel enrichment is live** (AbuseIPDB, GreyNoise, VirusTotal). Connectors: AWS
  (CloudTrail→S3, CloudWatch, StackSets, org discovery), GitHub (draft-PR remediation, encrypted PAT,
  repo allowlist), Slack (alert delivery). Datadog/Splunk/webhook catalogued, pending.

### 4.5 The AI agent arm — **the differentiator, and it's real** ✅🟡

- **Orchestrator:** LangGraph deep-agent (planner → worker → synthesizer → **HITL approver via
  `interrupt()`**), with budget caps (iterations/tasks/time/cost) and **per-task specialist routing**
  (each task carries an `agent_type`).
- **13 live specialist agents:** triage, optimization, log-watch, log-analytics, posture, ai-governance,
  report, workflow, workspace, project, task, user, ai-teammate. Plus a provenance/least-privilege stub.
- **~15 deterministic detectors** (sensors, no LLM on raw data): logwatch error/optimization, the AI
  finding router, the SSOT bridge, cloud-graph sync + attack-paths, weekly posture report,
  **agent-run-quality** (self-monitoring), project/task hygiene.
- **Tools carry risk levels** (READ / REVERSIBLE_WRITE / IRREVERSIBLE): `triage_finding`,
  `query_asset_graph` (grounds blast radius in the graph — *the differentiator in action*),
  `ioc_enrichment`, `retrieve_workspace_context` (RAG on every agent), `request_human_approval`.
- **RAG:** pluggable vector store (pgvector default), embeddings, query-rewrite + cross-encoder rerank +
  iterative self-verify; workspace- and role-scoped.
- **Response actions:** propose → approve → execute → rollback, with dry-run + credential vending. Live
  action: `REVOKE_SG_INGRESS`. Propose/rollback live; **approve-to-execute orchestration is minimal.**
- **Observability:** Langfuse tracing, `DeepRunLog` + live WebSocket events, rubric grading of agent
  answers.
- **Gaps:** the LLM planner is expected from the caller (not built-in), attack-path → findings emission
  is deferred, approve-to-execute isn't wired end-to-end, and most specialists beyond log/cloud are stubs.

### 4.6 The HUD — **polished blue-team surface, cosmetic red, some demo data** 🟡

Full CNAPP card suite on real API data (risk-score ring, findings, cloud posture, attack coverage, asset
graph, attack surface, compliance) with drillable lunar callouts, the threat map, kanban board, live log
stream. Ring/chrome are production-grade. **But:** the **red-team flip is cosmetic** (red modes' panel
lists are empty → cards vanish; red hex clicks dead-end); the recycle bin has no API; forecast is a stub.

_Update 2026-07-31 (FE #114):_ the fabricated demo cards are gone — OPERATIONS/RECON/INCIDENTS were
removed (their real equivalents, ACTIVE SCANS + SIGNALS/FINDINGS, already render live), and
SYSTEM/STATS/EVENT-VOLUME now read real facts (monitored regions, onboarding readiness, risk score) or
show an honest "coming soon". No fabricated numbers remain on the main HUD; the red-team lens and the
recycle-bin/forecast stubs are the remaining trust gaps.

---

## 5. Honest scorecard

| Capability | State |
|---|---|
| Platform (auth, tenancy, RBAC, billing, flags, audit, recycle-bin, branding) | ✅ **mature** |
| Findings SSOT + lifecycle + board sync | ✅ **real** |
| Prowler CSPM, Trivy SCA (hardened K8s Jobs) | ✅ real, **flag-gated off** |
| Asset graph + attack paths | ✅ built, **dark + not UI-wired** |
| MITRE ATT&CK coverage heatmap | ✅ built, **tagging Prowler/attack-path only; 5 techniques** |
| Compliance summary | ✅ real, **Prowler-only, failing-controls-only** |
| Log ingestion + SIEM-grade detection + threat-intel enrichment | ✅ **real** |
| Security metrics | 🟡 real backend, **not in REST API** |
| Deep-agent orchestrator + 13 specialists + detectors | ✅ **real** |
| Response actions (propose/rollback) | ✅ real; **approve→execute partial** |
| HUD blue-team CNAPP surface | ✅ **polished, real data** |
| Customer traces · red-team lens · runtime visibility · multi-cloud · ATT&CK-on-logs · metrics-in-UI · forecast · operational KPIs | 🟡 / ⚪ **partial → vision** |

---

## 6. Product vision (the north star)

**Auto-Sec is the AI-native security platform where the defender's, attacker's, and auditor's views share
one cloud graph, and AI agents close the loop from detection to reversible response — and from control to
audit-ready evidence.** It's the convergence play: **CNAPP** (see the exposure) + **CTEM** (prioritize &
*validate* what matters) + **Continuous Compliance** (*comply* — evidence it, with provenance) + **Agentic
SOC** (handle it) — unified because it's built on one graph and one reproducible agent framework.

- **The wedge (first real customer):** **AI-native teams shipping fast with AI-generated code**, on AWS,
  with real exposure (misconfigs, over-permissioned IAM, public data — *and now AI-introduced bugs like
  broken tenant isolation*) and *no SOC* — drowning in GuardDuty/Prowler noise, priced out of Wiz, and
  unable to adopt Dropzone (which assumes an existing SIEM/SOC). The pitch: **"the security team you don't
  have to hire — your AI SOC analyst that actually understands your cloud"** (validated framing, §2.1).
  Their felt pain isn't writing code; it's *knowing they're shipping safely.*
- **The moat:** (1) the **unified graph** makes triage *grounded* — agents reason over real
  asset/attack-path/ATT&CK context, not alert text — which is hard for analyst-only startups to
  replicate; (2) the **reproducible deep-agent arm** — each new "arm" (triage today; OSINT, recon,
  enumeration next, per the Kali-for-SOC vision) plugs into the same blueprint, so capability compounds.
- **The red/blue duality as CTEM's "validate" stage:** flip to the attacker's ATT&CK / kill-chain view to
  *prove* an exposure is reachable (BAS-like validation), then flip back to defend. Most CNAPPs stop at
  "here's a misconfig"; Auto-Sec can say "here's the attack path, mapped to ATT&CK, and here's the
  reversible fix."
- **The compliance (comply) lens — the third view:** the *same* graph + findings, mapped to framework
  controls and emitted as **audit-grade evidence with provenance** (where/when/how each artifact was
  generated). Because Auto-Sec *generates* the scans rather than scraping them from other tools, its
  evidence carries provenance a Vanta-style aggregator can't match. The wedge is **automation + provenance
  for teams past their first audit**, not a first-timer onboarding wizard (see §2.2, ADR 0009).

---

## 7. Strategic gaps & decisions

1. **Runtime visibility** — Gartner calls it table-stakes; we're scan/log-based. Do we need an
   eBPF/runtime signal, or lean into "agentless + AI" as the anti-agent position?
2. **Single-cloud (AWS)** — when does multi-cloud (Azure/GCP) become a deal-breaker for the wedge?
3. **ATT&CK tagging is partial** — tagging Trivy + logwatch findings is the concrete fix behind "the
   notes don't cite ATT&CK," and it's what makes the red-team lens complete.
4. **Red team is a shell** — commit to making it functional (ATT&CK kill-chain lens + attack-path
   validation) or de-emphasize until it's real?
5. **Flag-gating policy** — ✅ hardcoded cards removed (FE #114) and the demo workspace un-darkened
   (cloud-posture + asset-graph on real data; container-security left dark, no workload). Open decision:
   what's on by default per-workspace for real customers, and the pillar-enable UX (workspace-scoped
   `FeatureFlagRule`, never a global `default_enabled` flip).
6. **Metrics not in API** — small backend lift to unlock the OBSERVABILITY pane.

---

## 8. Suggested sequencing

A rough, honest order — **all against sample-onboarding data first**:

1. **Trust & clarity:** ✅ _shipped 2026-07-31_ — fabricated demo cards removed/de-faked (FE #114);
   CNAPP engine confirmed already un-darkened on the sample workspace (real data). What a user sees on
   the main HUD is now real or an honest "coming soon".
2. **ATT&CK everywhere:** tag log + container findings → a technique on every finding → cite it inline on
   alert notes / board cards (feeds both the OBSERVABILITY notes and the red lens).
3. **OBSERVABILITY pane:** rename LOGS → OBSERVABILITY; expose metrics via API; tabbed
   Logs / Metrics / (Traces stub).
4. **Red = real:** make the red lens the ATT&CK kill-chain + attack-path view over the same findings
   (distinct cards, not just color).
5. **Close the loop:** wire approve → execute for response actions.

---

## 9. Open questions

- Does the **wedge** (cloud-native SMB / mid-market; "AI SOC analyst that understands your cloud") match
  the interviews?
- Is the **convergence framing** (CNAPP + CTEM + Agentic SOC) the positioning, or lead with one
  ("AI SOC" vs "CNAPP")?
- How much to **lean on red/blue** as a headline vs. a power-user feature?

---

## 10. Sources

Market research (2025/26), for the framing in §2 and §6:

- Gartner 2025 CNAPP Market Guide takeaways — [Orca](https://orca.security/resources/blog/gartner-2025-market-guide-for-cnapp/),
  [Wiz](https://www.wiz.io/blog/unpacking-cnapp-gartner-market-guide),
  [Sysdig ("runtime no longer optional")](https://www.sysdig.com/blog/2025-gartner-cnapp-market-guide)
- CTEM / Exposure Management convergence — [Wiz CTEM](https://www.wiz.io/academy/cloud-security/continuous-threat-exposure-management),
  [Market Guide 2025](https://softwareanalyst.substack.com/p/market-guide-2025-evolution-of-modern)
- Agentic AI SOC category — [UnderDefense](https://underdefense.com/blog/agentic-soc-platforms/),
  [Prophet Security](https://www.prophetsecurity.ai/)
- MITRE ATT&CK for cloud (kill-chain vs ATT&CK; 40–60 technique focus) —
  [Cloud Security Alliance](https://cloudsecurityalliance.org/blog/2026/05/22/mitre-att-ck-for-cloud-a-practitioner-s-guide-to-detection-coverage)
- Security + observability convergence —
  [APMdigest](https://www.apmdigest.com/convergence-of-observability-and-security-2),
  [Security Boulevard](https://securityboulevard.com/2025/10/guest-essay-observability-is-no-longer-passive-its-now-a-real-time-driver-of-security-action/)
