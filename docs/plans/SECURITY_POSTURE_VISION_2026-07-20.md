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

### 3.3 `cloud_posture_agent` — CSPM/CIEM (Phase 2)
The security-engineer view: roles with root/`*` access mapped, SCP coverage
per account, access-key age, MFA-on-root, wildcard-policy inventory. Reads
**nightly snapshots** (never live-scans mid-chat) via the existing STS
adapter + a read-only audit role rolled out to linked accounts.

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
2. **Nightly `CloudPostureSnapshot`** per `AwsAccountLink` (read-only IAM/SCP
   facts as rows).
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
| **3** | `CloudPostureSnapshot` nightly task → `cloud_posture_agent` → HUD POSTURE module w/ persona lenses | Read-only IAM audit role per linked account (operator dependency) |
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
