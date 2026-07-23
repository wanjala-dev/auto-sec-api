# Security Posture — Product Vision & Phased Plan

**Date:** 2026-07-20 · **Status:** Direction approved in discussion; Phase 1 pending go
**Origin:** Henry's posture brain-dump (persona-dependent posture, cloud/IAM visibility,
AI governance, attack simulation, "chat with the logs") + web research on posture
scoring, SOC KPIs, CTEM, and the AI-SOC vendor landscape.

---

## 1. The core insight: posture is persona-dependent

"Security posture" means different things to different people, and the market
splits exactly this way:

| Persona | What posture means to them | Industry category |
|---|---|---|
| **Security engineer / operator** | Where do we stand with AWS SCPs? Which roles have root access? Which roles carry `*` (admin) policies? Access levels and permissions, mapped out. | CSPM / CIEM (Wiz-style drill-down) |
| **CSO / C-suite** | Dashboard: findings trend, response-time bands, log lines/day, security spend/day compounding per week/month — bar graphs, not tables. | Executive posture reporting (SecurityScorecard-style) |
| **SOC lead** | Is the detection-and-response machine working? Backlog, triage latency, what the AI absorbed vs. escalated. | SecOps metrics (MTTD/MTTR canon) |
| **AI governance owner** | What is the AI itself doing? Which roles did it use? Who granted it which permissions? Can we kill it right now? | AI-SPM (new category; OWASP Agentic Top 10, Dec 2025) |

**Design rule:** ONE posture fact store (deterministic aggregation tables),
MULTIPLE lenses. Never a parallel data path per persona. Sharing = a posture
report artifact generated through the templates kernel (same pipeline as any
generated report → link/PDF for the CSO falls out for free).

---

## 2. What the research says (2026-07-20 sweep)

1. **Composite posture scores are the industry's most-gamed metric.**
   Microsoft Secure Score and AWS Security Hub compute passed/enabled ratios;
   documented failure modes: suppressing failed findings *raises* the score,
   teams chase high-point items that don't close real exposure, and 100% ≠
   secure — it means "you enabled the controls the score measures."
   → **No single "posture score: 87" in v1.** Components first. If a score is
   ever added, suppressed findings must count *against* it.

2. **The SOC KPI canon comes with real benchmarks** we can compute from data we
   already store: MTTD 30min–4h; MTTR by severity (critical 1h → low 8h); mean
   time to investigate 10min–1h; acknowledgment latency (critical 20min);
   FP-rate bands by severity; **use medians, not means** (outlier resistance).
   Alert fatigue is the industry wound (avg ~3,000 alerts/day, ~70min per
   investigation) — our posture report should quantify *toil absorbed by the
   agents* (auto-triaged vs. escalated `needs_human`).

3. **Gartner CTEM (Continuous Threat Exposure Management)** is the right
   narrative skeleton — five stages: Scoping, Discovery, Prioritization,
   Validation, Mobilization. Our pipeline already maps onto it:
   log-watch = Discovery · severity/frequency = Prioritization ·
   grounded verification + rubric grading = **Validation** (our real
   differentiator) · draft PRs + board cards = Mobilization.

4. **Vendor landscape:** the AI-SOC wave (Prophet, Dropzone, Radiant, 7AI)
   leads with *triage agents that show their reasoning* — which we have.
   Posture reporting is still CSPM-checklist-shaped. An **operations-posture**
   agent ("how is our detect-and-respond machine performing, with evidence")
   is a differentiated angle none of them lead with.

Sources: MS Secure Score docs, AWS Security Hub scoring docs, Prophet's "SOC
metrics that matter", Vectra alert-fatigue research, ctem.org, UnderDefense
AI-SOC vendor comparison.

---

## 3. Fleet audit — what exists vs. what the vision needs

**Existing agents:** `orchestrator` (planner, no tools) · `log_watch`
(detection) · `triage` (per-finding fix + draft PRs) · `optimization`
(log-volume advice) · `workspace` / `task` / `project` / `user` (org utility).
**Detectors:** logwatch (+ finding router), run_quality, projects, tasks.

**Existing foundations the vision can stand on:**
- AWS: `AwsOrganizationConnection`, `AwsAccountLink`, `StsOrgAdapter`
  (cross-account assume-role works today) — the doorway to IAM/SCP scanning.
- Logs: ingest checkpoints, `LogPatternRollup` (temporal aggregation),
  `SinkConnector`, S3 log shipping from the wanjala demo as a live feed.
- Governance: `ToolRisk` tiers, per-agent capability grants (`open_draft_pr`),
  HITL approval endpoints, `GitHubConnection` (scoped, encrypted), action
  provenance on board cards, `run_telemetry` + rubric verdicts + human votes.
- Audit context (ported), templates kernel (report artifacts).

**Gaps → four new standalone specialists.** (Explicit rule from Henry: none of
this piles onto triage or log_watch — separation keeps their tool lists small
and routing precise.)

### 3.1 `posture_agent` — SOC-ops posture (Phase 1)
Read-only aggregator across the other agents' outputs. Tools:
- `get_findings_posture` — open by severity/kind, `needs_human` backlog,
  oldest-untriaged age, triaged-today.
- `get_response_kpis` — median detection→finding, finding→triage latency,
  triage MTTR per severity, each reported against the industry bands.
- `get_fleet_health` — dispatch success, rubric pass rate, cost/day,
  human vote ratios; toil absorbed (auto-triaged vs. escalated).
- Persona lens parameter: engineer (drill-down + evidence) vs. executive
  (trends + business metrics: lines/day, spend/day compounding).
CTEM-stage narrative. LLM narrates ONLY tool output (no LLM over raw data).
Routing eval case: "what is our security posture?" → `posture_agent`.

### 3.2 `log_analytics_agent` — "chat with the logs" (Phase 1)
Answers: "how many SSH attempts this week?", "5xx this month — spike or
sustained? DDoS?", "where did attacks come from?", "how many SQL injections?",
"app errors/warnings by area".
**Architecture rule (Henry's instinct, codified):** counting questions NEVER
hit RAG. NL → deterministic aggregation queries over widened rollups. The
planner routes: counts/trends → this agent; narrative/docs → RAG. Tools:
- `query_log_rollups(metric, window, group_by)`
- `classify_trend(metric, window)` → spike | sustained | quiet (hourly buckets)
- `top_sources(metric, window)` — source-IP/agent rollups

### 3.3 `cloud_posture_agent` — CSPM/CIEM, **Prowler-as-engine** (Phase 3)
The security-engineer view: roles with root/`*` access mapped, SCP coverage
per account, access-key age, MFA-on-root, wildcard-policy inventory, and the
broader cloud-config surface. Reads **nightly snapshots** (never live-scans
mid-chat) via the existing STS adapter + a read-only audit role rolled out to
linked accounts.

**Decision (2026-07-22): do NOT hand-roll the cloud-config scanner — embed
[Prowler](https://github.com/prowler-cloud/prowler) (open-source, Apache-2.0)
as the detection engine.** This is the `no-reinventing-the-wheel` rule applied
at the tool tier, and it flips Phase 3 from "write IAM/SCP check libraries for
years" to "wrap best-in-class OSS."

- **Why it fits**: Prowler is **Python** (Boto3 / Azure SDK / GCP client), so
  it runs in a Celery worker or a dedicated container and assumes-role into
  linked accounts *exactly* the way `StsOrgAdapter` + `AwsAccountLink` already
  do — the plumbing is plumbing we already built. Hundreds of maintained checks
  with **compliance frameworks baked in** (CIS, **SOC 2, PCI-DSS, HIPAA**, NIST
  800/CSF, FedRAMP, ENS). JSON/OCSF output.
- **The engine/SOC split (same architecture as our log story)**: Prowler is the
  "SIEM-equivalent for cloud config" — it emits raw findings; **our AI layer is
  the value-add on top.** Nightly Prowler scan → JSON → mapped into our existing
  `Task` finding contract (`source_type="ai.cloud_posture"`, severity mapped,
  deduped, aggregate-don't-dump) → the **triage agent grounds/verifies/
  prioritizes**, the **posture agent** rolls it into the CTEM narrative, the
  **board tracks remediation**. Prowler is NOT a competitor to what we built —
  it's the cloud detection engine our analysts were missing. Our moat stays the
  AI triage / verification / posture / governance layer, never the scanner.
- **Discipline**: nightly per-account (already the §3.3 rule), map Prowler
  severities to ours, feed only *actionable* findings to the board (hundreds of
  checks × N accounts is a firehose — same aggregate-first rule as logs).
- **Multi-cloud future-proofing (free)**: Prowler also covers Azure / GCP / K8s
  / GitHub / M365 — one integration future-proofs multi-cloud without per-cloud
  scanners of our own.
- **Embed the OSS CLI/SDK (Apache-2.0), NOT Prowler Cloud** (their SaaS). Clean
  to vendor.
- **Unchanged operator dependency**: the read-only IAM audit role rollout to
  linked accounts (Henry's infra call) — that role now feeds a far richer
  scanner. Phase 3 still waits on that green light.

### 3.4 `ai_governance_agent` — AI-SPM (Phase 3)
Dogfoods our own governance: which agent used which tool at which risk tier,
HITL approvals granted/denied, capability grants (who enabled draft-PR, when),
credential scopes (GitHubConnection), MCP/tool inventory, and the **kill
switch** — `Workspace.ai_teammate_enabled` is the circuit breaker today; it
needs a first-class red button in the HUD + audit trail, not a DB flag.

### 3.5 `threat_sim_agent` — MITRE / simulation (Phase 4)
1. **ATT&CK coverage map** — static technique tags on detectors/findings;
   report coverage vs. the ~65% pragmatic target (not 100%).
2. **Tabletop simulation** — walk ATT&CK paths against our own posture
   snapshots ("assume this `*`-role key leaks; SCP gaps allow X") → emits
   pre-validated findings.
3. **True BAS** (benign attack execution) — much later; safety + scope gate.

---

## 4. The aggregations (the real work, built before the agents that read them)

1. **Widen `LogPatternRollup` taxonomy + hourly buckets:** auth/SSH-attempt
   class, HTTP status classes (5xx), attack signatures (SQLi patterns, scanner
   UAs), source-IP rollups, app errors/warnings by service. Hourly buckets are
   what make spike-vs-sustained/DDoS answerable deterministically.
2. **Nightly Prowler scan → `CloudPostureSnapshot`** per `AwsAccountLink`:
   Prowler runs under the read-only audit role, its JSON is mapped to snapshot
   rows + `ai.cloud_posture` findings (severity-mapped, deduped). We do NOT
   author IAM/SCP checks ourselves — see §3.3.
3. **Daily AI-action rollup** for governance charts.
4. **Static MITRE technique mapping table** on detectors/findings (no LLM).

---

## 5. Navigation & sharing

- **POSTURE module** in the HUD module grid, persona tabs (ENGINEER /
  EXECUTIVE), rendering the same aggregates the agents read — bar graphs for
  lines/day, spend/day, findings trend, KPI bands.
- **Sharing:** posture report artifact via the templates kernel → exportable /
  linkable like any generated report.

---

## 6. Phases

| Phase | Contents | New ingestion needed |
|---|---|---|
| **1** | Rollup taxonomy widening → `posture_agent` + `log_analytics_agent` + routing eval cases | None — rides existing log ingest + board/telemetry data |
| **2** | `ai_governance_agent` + kill-switch surfacing + daily AI-action rollup (promoted: AI-SPM is early+hot, boards want AI-risk reporting, zero new ingestion) | None — governance data exists |
| **3** | **Prowler-as-engine** nightly scan → `CloudPostureSnapshot` + `ai.cloud_posture` findings → `cloud_posture_agent` → engineer lens on the POSTURE module (+ compliance framework coverage: SOC 2 / PCI / HIPAA) | Read-only IAM audit role per linked account (operator dependency) + Prowler OSS vendored |
| **4** | MITRE coverage map → tabletop `threat_sim_agent`. Standalone BAS DROPPED (see §8) | Static mapping first |

Each phase is a shippable product on its own — no throwaway stages.

---

## 7. Open decisions

- Phase 1 go/no-go (recommended: go).
- Whether `posture_agent` also runs as a weekly scheduled detector posting a
  posture-report finding to the board (recommended: yes, same pattern as
  `AgentRunQualityDetector`).
- SIEM read-IAM for the S3 log feed (operator item, pre-existing).
- BAS safety model (Phase 4 — deliberately unscoped for now).


---

## 8. Validation review (2026-07-20, second research pass)

Henry asked for a thorough re-review before execution. Six research angles;
verdict: **route validated, three adjustments applied** (already reflected in
the phases table above).

### Confirmed
1. **CTEM gap = the opportunity.** Market ~$1.3–2.7B, 11–13% CAGR; 87% of
   security leaders recognize CTEM's importance but only **16% have
   operationalized it**. Mid-size orgs can't build the program themselves;
   our pipeline implements the five stages natively — "CTEM in a box."
2. **Persona lenses = the documented board pain.** IANS 2026: only 29% of
   boards rate CISO reporting "very effective"; missing piece is
   *forward-looking* content (trend trajectory, scenarios, financial
   exposure). NACD 2026 prescribes a five-category board framework the exec
   lens should adopt. **47% of boards say AI-driven-risk reporting needs
   improvement** — feeds the AI-governance agent's case.
3. **AI-SOC category has real money**: Exaforce $125M Series B (May 2026),
   Citi Ventures → Prophet. Buyer skepticism about plausible-but-wrong AI
   output (Security Copilot distrust) validates our grounded-verification /
   show-the-evidence architecture as the differentiator.
4. **Chat-with-logs is table stakes**: Datadog Bits, Elastic AI Assistant,
   Splunk, Grafana all shipped NL telemetry query within ~18 months. Elastic's
   split (query-generation for data, RAG for knowledge) matches our
   aggregation-first rule exactly.
5. **AI-SPM is early and hot**: Wiz/Noma/Orca/PANW shipped; Noma launched
   agent + MCP access control (Henry's exact ask). Only 29% of orgs feel
   prepared to secure agentic AI; 6% have an advanced strategy.
6. **Mid-market wedge confirmed**: 83–90% false-alarm rates, 40% of alerts
   uninvestigated, MDR "strained by scale, cost, visibility."

### Counter-signals → adjustments
- **Dashboard fatigue is brutal** ("single pane of glass" critique: teams
  drown in dashboards that surface risk without driving action; consolidation
  ≠ clarity). → **Adjustment 1:** POSTURE module is action-linked, not a
  graph wall — every posture fact drills to the finding/card/draft-PR that
  remediates it. Persona lenses (separate views) are what the critique
  prescribes; our Mobilization pipe is the structural antidote.
- **BAS is weak for our ICP**: SMB adoption ~28%; cost (35%), skill gaps
  (55%), integration delays (45%), shelfware reputation. → **Adjustment 2:**
  standalone BAS dropped from the roadmap. Phase 4 = ATT&CK coverage map +
  tabletop simulation against our own posture snapshots. Payload-executing
  BAS only with real customer pull (or via partner).
- **Boards want forward-looking + AI-risk reporting.** → **Adjustment 3:**
  `ai_governance_agent` promoted to Phase 2 (zero new ingestion, hot
  category); cloud posture slides to Phase 3 (operator dependency: IAM audit
  role rollout). Exec lens adopts NACD's five categories + a forward-looking
  section (backlog aging trajectory, trend deltas).

### Key sources
Gartner CTEM roadmap + Vectra CTEM adoption stats · Grand View CTEM market ·
IANS board-reporting research · NACD 2026 Director's Handbook · Citi Ventures
Prophet investment · UnderDefense AI-SOC mid-market pricing survey · Datadog
Bits / Elastic AI Assistant docs · Wiz AI-SPM academy · Noma agentic access
control launch · Mordor BAS market (SMB barriers) · Reclaim Security /
Tripwire single-pane critiques.

---

## 9. Positioning — where auto-sec sits in the SIEM / SOC / SOAR / XDR map (2026-07-21)

Taxonomy refresher: the **SIEM** aggregates/correlates/detects/alerts (the sensory
system and alarm); the **SOC** is the human function that triages, investigates,
and responds; **SOAR** is the automation layer between them; **XDR** blends
detection+response into one integrated product.

### What we've built, mapped honestly

| Layer | What auto-sec has | What it is NOT |
|---|---|---|
| **SIEM (a deliberate slice)** | Fluent Bit → S3 → checkpointed scan → aggregate-at-ingest (`LogPatternRollup`, `LogMetricBucket` hourly security metrics). Detection = code-defined detector registry. Raw stays in cheap S3. | A general SIEM: no searchable raw store, no user-authored correlation rules (Sigma), one ingest source today. |
| **SOC (our strongest layer)** | Triage agent = Tier-1/2 analyst (grounded verification, rubric grading, draft-PR fixes). Router→specialists = escalation paths. Kanban = case management. `needs_human` = human escalation. Plus the near-unique layer: **QA of the AI analysts** — rubric verdicts, human votes, run telemetry, run-quality detector, eval-gated planner prompts. | A staffed 24/7 human SOC (that's the point). |
| **SOAR (dormant asset)** | Draft-PR remediation = an HITL response playbook. Kill switch = containment. **The ported workflow engine (triggers→conditions→actions→waits) is a SOAR playbook engine sitting unused** — pointing it at security response is a port, not a build. | Connector-rich Torq/Tines competitor. |
| **XDR** | Nothing — no endpoint/network telemetry. | Don't pretend. Connector territory, later or never. |
| **AI-SPM + CTEM (outside the classic taxonomy — our differentiation)** | Governance agent + audited kill switch (govern the AI SOC itself); posture agent + KPI bands + dashboard. | — |

### The market signal (research 2026-07-21)

- **The converged platform is winning.** 2026 buyer analyses: the winning model
  is log management + detection + response + reporting in ONE platform, not
  fragmented categories; mid-market picks MDR services chiefly because it cannot
  staff 24/7 coverage (4.8M-person workforce gap).
- **SIEM ingest pricing is the industry's hated tax.** Panther ≈ $110–170K/yr at
  50GB/day mid-market; Anvilogic floors ≈ $80K/yr; Rapid7 markets asset-based
  pricing explicitly as "eliminating ingest anxiety." Our aggregate-first
  architecture (rollups in Postgres, raw in S3) is a structural cost story.
- **The funded AI-SOC startups (Prophet, Dropzone, Radiant, 7AI) sit ON TOP of
  an existing SIEM** — they assume the six-figure SIEM bill is sunk. Radiant
  bundling "integrated log management as a SIEM-cost counterweight" is the
  strongest competitor validation of our bundled direction.

### The positioning

**AI SOC-in-a-box for the SIEM-less mid-market** — the MDR alternative as a
product: slim ingest + detection + AI analysts + case board + posture reporting
+ AI governance, one platform, for orgs whose current SIEM is grep-and-hope and
whose SOC headcount is zero. Not "a worse Splunk plus a worse Prophet" — the
converged shape the market is voting for, at a cost structure incumbents can't
copy without cannibalizing per-GB revenue.

The BYO-SIEM alert-connector lane (Prophet's lane) is a later expansion, not
the lead — crowded, funded, and it forfeits the cost-structure advantage.

### Gaps between here and that positioning being real

1. **Connector breadth** — CloudWatch, syslog, and one identity source
   (Okta/GitHub audit logs); identity is the actual mid-market attack surface.
2. **Chat-authored detections** — NL description → agent proposes a
   deterministic detector → HITL approve. On-brand alternative to a Sigma
   editor; keeps the no-LLM-over-the-firehose rule.
3. **Workflow engine → response playbooks** — agent-proposed, HITL-gated
   security playbooks (finding → enrich → notify → contain-with-approval).
4. **Bounded raw search** — Athena/DuckDB over the existing S3 bucket, not a
   new store.
5. **Retention/compliance floor** — regulated mid-market buys on 1yr+ log
   retention + framework attestation (HIPAA/PCI/SOC 2). **Prowler (§3.3) closes
   the config-compliance half for free** (its checks are framework-mapped); the
   remaining half is the **log-retention** story (raw in S3 already satisfies
   the retention bytes — needs the retention-policy + attestation surface, not
   new storage).
6. Housekeeping: HUD mock-data cards (CASES %, INTEL FEEDS), multi-tenant
   scale proof.

### Sequencing (extends the phases above)

Finish in-flight visibility (POSTURE module, web push) → connectors →
workflow-engine playbooks → chat-authored detections → bounded raw search +
compliance floor.

Key sources: siemcostcalculator.com (Panther), anvilogic.com/siem-replacement,
reco.ai traditional-SIEM-vs-AI-native, underdefense.com managed-SIEM-vs-MDR +
ai-soc-for-mid-market, n-able.com mdr-vs-siem.

---

## 10. The CNAPP lens (2026-07-23)

Henry asked whether autosec can become a **CNAPP** (Cloud-Native Application
Protection Platform). The answer reframes this vision, it doesn't replace it:
**autosec's CNAPP is the convergence of pillars already planned here — no new
roadmap, no new bounded context beyond the two already designed.**

### What "CNAPP" maps to in our existing plan

| CNAPP pillar | Where it already lives | Status |
|---|---|---|
| CDR (runtime detection) | CloudTrail ingest + detector registry | shipped / POC |
| CSPM + CIEM (cloud config posture) | §3.3 `cloud_posture_agent`, **Prowler-as-engine**, nightly `CloudPostureSnapshot` | Phase 3, gated on the read-only IAM audit-role rollout |
| Attack-path / asset graph ("toxic combinations") | `PROVENANCE_ACCESS_GRAPH_2026-07-17.md` — Actor→Resource→Grant→ProvenanceEvent, BloodHound-style | designed; **Slice 0 unblocked** (internal-only, zero new creds) |
| AI-SPM | §3.4 `ai_governance_agent` | Phase 2 (partly shipped) |
| Agentic triage → **validation → branded report** | triage agent + rubric/grounded verification + templates kernel | shipped — the differentiator |

### The synthesis (the piece neither doc drew explicitly)

The crown jewel is **wiring Prowler cloud-posture findings *into* the provenance/
access graph.** Prowler tells us *a role carries `*` admin and an S3 bucket is
public*; the provenance graph tells us *which actor holds that grant and whether
anything ever exercised it*. Correlating the two **is** attack-path / toxic-
combination analysis — the thing Wiz sells as its Security Graph — expressed over
machinery we already have. A confirmed path becomes a triage-board finding, gets
**validated** (grounded verification / tabletop `threat_sim_agent`, §3.5), and
falls out as a client-ready posture+pentest report through the templates kernel.
*Validated* posture + auto-report is an artifact neither Wiz nor the AI-SOC pack
(Dropzone/Prophet) produces.

### Competitive framing (mid-market, confirmed ICP)

- **Do not out-scan Wiz/Orca/Prisma.** Their moat is years of policy content +
  agentless snapshot infra. We wrap **Prowler** (already decided, §3.3) and put
  the value in the AI correlation/validation/report layer.
- **The real free-tier threat is Prowler App itself** (Apache-2.0, ships its own
  attack-path via Cartography+Neo4j). Our paid wedge over "run Prowler yourself"
  is **autonomy** — triage that kills the 70–90% noise, validated attack paths,
  and the report — for orgs whose SOC headcount is zero. This reinforces §9's
  "AI SOC-in-a-box for the SIEM-less mid-market" positioning.

### Decision: stay Postgres-first — drop Neo4j / Cartography

An initial CNAPP sketch proposed adopting **Cartography + Neo4j** for the asset
graph. **Rejected**, for two standing reasons already in our plans:
1. It contradicts the deliberate **Postgres-first cost-structure moat** (§9) and
   the provenance doc's explicit "prefer Postgres, add a graph store only if
   traversal depth demands it."
2. Cartography would be a **redundant second inventory engine** next to Prowler
   (our chosen cloud-config scanner) — reinventing plumbing we already have.

The provenance/access graph stays **Postgres (adjacency + recursive CTE)**. The
CNAPP attack-path use case is precisely the scenario that *might* later justify a
dedicated graph store — re-evaluate then, against real traversal depth, not now.

### Sequencing delta

No change to the phase table. The CNAPP framing simply makes the **provenance
graph a first-class MVP pillar** (it was a separate "third pillar" doc) and names
the **Prowler-findings → graph** correlation as the Phase-3 payoff. Immediate
buildable step: **`PROVENANCE_ACCESS_GRAPH` Slice 0** (internal-only graph from
`EntityAuditLog` + `ai/actions` + identity sessions) — unblocked today; cloud
posture (Phase 3) still waits on the operator IAM audit-role rollout.
