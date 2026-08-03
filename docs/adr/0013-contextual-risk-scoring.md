# ADR 0013 — Contextual Risk Scoring: the 4-signal blend (CVSS + EPSS + CISA KEV + graph-exposure) that ranks the few findings that actually matter

Status: Proposed (2026-08-03)
Relates to: **ADR 0004** (the CNAPP Finding SSOT + Asset-graph spine — this ADR *is* that ADR's
**Phase 6**: "attack-path + contextual-risk background job → materialized table → HUD"), **ADR 0006**
(`ScannerPort` / `ScanExecutionBackend` — the driven-adapter-behind-a-port precedent a `VulnFeedPort`
mirrors), **ADR 0008** (multi-source log ingestion behind a `LogSourcePort` — the same multi-provider,
pinned-source seam pointed at threat-intel feeds), and the `cloud_graph` context (which already owns the
**exposure** signal and a live per-workspace `RiskScoreCalculator`).

## Context

Auto-Sec's operators keep saying the same thing five different ways. William (3rd operator interview,
2026-08-02, ex-Clio SIEM, terabytes of logs/day): *"Don't show me 50 things. Tell me the few that
actually matter, why, your recommendation, and let me accept the risk knowingly."* Tom and Andrea say
the equivalent from the builder and compliance angles. The **"what do I need to know today" brief** the
HUD is being reshaped around (the Tom+William convergence) is only as good as the **ranking substrate it
sorts on** — and today there is no such substrate at the finding grain. The findings list orders strictly
by `-last_seen_at` (`DjangoFindingRepository.list_findings`); recency is not risk. This ADR designs the
ranking substrate.

**This is also the moment the industry made the call for us.** On **2026-06-10 CISA issued Binding
Operational Directive 26-04**, the first time a government formally **retired CVSS as the basis for what
to fix** and replaced it with a **four-question model**: *is the asset internet-**exposed**? is the CVE in
**KEV** (confirmed exploited)? is exploitation **automatable**? does it hand the attacker **total
compromise**?* A vulnerability that is all four — internet-facing, automatable, full-takeover, actively
exploited — is a 3-day emergency.[^bod2604][^picus] Our four signals map onto those four questions almost
one-to-one, and CVSS-alone is exactly the noise generator BOD 26-04 exists to kill. Ranking on raw CVSS
(or raw severity) is what produces the wall of "criticals" nobody can action.

**The signals, and why each one alone is insufficient:**

- **CVSS / severity — the technical-impact axis (we already have it).** Every finding carries a
  normalized `Severity` (`components/shared_kernel/domain/security.py`), and Trivy CVE findings carry a
  CVE id. But CVSS answers *"how bad if exploited"* — not *"will it be."* ~60% of the CVE population is
  CVSS 7.0+; severity alone cannot rank.
- **EPSS — the exploitation-**probability** axis (net-new).** The **Exploit Prediction Scoring System**
  (FIRST.org) publishes, per CVE, a daily probability [0–1] that it will be exploited in the next 30 days,
  plus a percentile. It is the industry answer to *"which of these thousand criticals is actually likely."*
  A CVSS-9.8 with EPSS 0.0004 is not a fire; a CVSS-6.5 with EPSS 0.86 might be.[^epss][^epssdata]
- **CISA KEV — the **confirmed-exploited** axis (net-new).** The **Known Exploited Vulnerabilities**
  catalog is CISA's authoritative list of CVEs with *evidence of active exploitation in the wild*. KEV is
  not a prediction — it is a fact, and it must **dominate**: a KEV CVE is being exploited right now,
  regardless of what CVSS or EPSS say.[^kev][^kevfeed]
- **Graph-exposure — the **reachability** axis (we already have it, fully built).** `cloud_graph` already
  computes real `CloudAsset.exposure` (`public | internal | private`) from **actual reachability** — a
  public IP or a public-subnet route to an internet gateway **and** a security group open to `0.0.0.0/0`
  (`boto3_inventory_adapter.py`), with a Prowler-derived heuristic fallback (`exposure_classifier.py`).
  This is BOD 26-04's question #1, already answered per asset. An internet-facing finding is a different
  animal from the identical finding on a private-only host.

The value is not any one signal — it is the **blend**: *"KEV-listed, EPSS 0.9, on an internet-facing
box"* is the ~1% that forms real attack paths; *"CVSS-critical, EPSS 0.0002, private, not in KEV"* is
noise. That reduction — from the wall to the few — is the CNAPP thesis (ADR 0004) and William's pay line:
*"actionable insight … IS why people pay."*

### What already exists (grounding — reuse, don't rebuild)

A 6-agent code sweep (2026-08-03) confirmed the scaffolding for this ADR is **already deliberately laid**:

- **The value objects.** `Severity`, `FindingStatus`, `AssetUrn`, `NormalizedFinding`, and — decisively —
  **`RiskBand.from_score(0–100)`** all live in `components/shared_kernel/domain/security.py`. `RiskBand`'s
  docstring says it in as many words: *"The numeric contextual-risk score (0–100) is computed by the
  **Phase-6 background job (ADR 0004 §6)**; from_score gives the provisional banding until that lands."*
  **This ADR is that Phase-6 job.**
- **The Finding SSOT.** The `findings` bounded context is real: `FindingEntity`, the `Finding` model
  (`infrastructure/persistence/findings/models.py`, indexed on `(workspace, severity, -last_seen_at)` and
  `(workspace, asset_urn)`), `ListFindingsQuery`, `DjangoFindingRepository`. CVE ids already ride in the
  OCSF `attributes` bag (`trivy_normalizer.py` writes `attributes.vulnerability_id` = the `CVE-…`/`GHSA-…`
  id, plus `pkg_name`, `installed_version`, `fixed_version`).
- **The exposure signal, fully built** — `cloud_graph`'s `CloudAsset.exposure` (real boto3 reachability +
  heuristic), keyed by `AssetUrn`, already consumed by the attack-path analyzer, with a read use case
  (`get_exposure_summary_use_case.py`).
- **The materialized-table + Celery pattern, twice over.** `WorkspaceAttckCoverage` (a per-workspace
  materialized heatmap recomputed by `findings.recompute_attck_coverage`, idempotent, `soft_time_limit=120`)
  and **`AttackPath`** (`infrastructure/persistence/cloud_graph/models.py`: a fully denormalized ranked
  view with `risk_score` FloatField 0–100, `risk_band`, index `(workspace, -risk_score)`, recomputed via
  `replace_for_workspace`). These are the exact templates for a materialized per-finding risk table.
- **An explainable risk calculator to build on / converge with.** `cloud_graph`'s live
  `RiskScoreCalculator` already returns `RiskScore(value, band, factors)` with a
  `RiskFactor(key, label, points, detail)` breakdown — deterministic, no LLM. It is **per-workspace**
  (attack-path scores + open crit/high/med counts, capped), **not per-finding**, and **does not fold in
  exposure or EPSS/KEV directly**. It is the seed the per-finding scorer generalizes.
- **The `ScannerPort` + registry + pinned engines** (`aquasec/trivy:0.58.0`,
  `toniblyx/prowler:5.36.0@sha256:…`) — the driven-adapter-behind-a-port shape a `VulnFeedPort` copies.
- **A daily-beat + dated-snapshot precedent** — nightly `schedule_cloud_posture_scans` (02:00) and the
  `AiActionDailyRollup` recompute; and, for pulling *external* data on a schedule, the assume-role windowed
  S3 read in `integrations/log_ingest_service.py` and the reference-data lookup `maxmind_geoip_adapter.py`
  behind `geoip_port`.

### What is genuinely NET-NEW

Numeric **CVSS + EPSS storage**; **external threat-feed ingestion** (EPSS daily CSV + CISA KEV JSON) with
**dated snapshots**; a **per-finding materialized contextual-risk table**; folding **exposure directly**
into a per-finding score; and the **risk-ranked findings read** (list re-rank + Today brief).

### Grounding — research (what shapes the model decisions)

- **CVSS alone is officially dead for prioritization** (BOD 26-04); the durable practice is **CVSS ×
  EPSS × KEV × exposure/asset-context**, not any one in isolation.[^bod2604][^picus][^zafran]
- **KEV dominates.** Confirmed-exploited is a fact, not a prediction; the consensus workflow patches KEV
  **first** (24-hour class), then EPSS-high, then everything else.[^tiering][^zest]
- **EPSS gates the "critical-but-unlikely."** FIRST publishes **no single threshold** — the cut depends on
  patch capacity — so the threshold must live in **one tunable place**, not be hard-coded across call
  sites.[^epss][^tiering] (This mirrors `RiskBand.from_score`'s "keep thresholds in one place so tuning is
  a single edit.")
- **Explainable beats black-box.** William: *"make the person a fan of what they're risking."* The score
  must carry a **factor breakdown** ("KEV-listed +40, EPSS 0.86 ×1.8, internet-facing ×1.0"), exactly the
  `RiskScore.factors` shape we already ship — never an opaque number.
- **Feeds are third-party data a security tool ingests → they must be pinned/snapshotted** (`pin-versions.md`).
  Never live-fetch per-request/per-scan; pull once on a schedule into a **dated, version-stamped snapshot**
  and score against the stored snapshot, so scoring is reproducible and a feed outage can't stall triage.

## Decision

Ship contextual risk as **ADR 0004 Phase 6**: a **per-finding, background-materialized, explainable
0–100 contextual-risk score** that blends **CVSS/severity (impact) × EPSS (likelihood) × KEV
(confirmed-exploited, dominant) × graph-exposure (reachability)**, computed by a Celery job over the
Finding SSOT, written to a materialized `FindingRisk` read table, and read via CQRS to re-rank the
findings list and feed the "Today" brief. It is composed almost entirely from parts we already own; the
only net-new infrastructure is the threat-intel feed ingestion.

### D1 — The blend: four signals mapped to BOD 26-04's four questions, KEV dominant, EPSS gating, exposure amplifying

The score is a **transparent, documented function**, not a model. Its shape (not its exact constants) is
what this ADR fixes; constants live in **one tunable module** (see D6), like `RiskBand.from_score`.

| Signal | BOD 26-04 question | Role in the blend | Source |
|---|---|---|---|
| **CVSS / Severity** | Technical impact ("total compromise?") | **Impact base** `I ∈ [0,1]` | CVSS base score from `attributes` when present, else `Severity.rank` mapping |
| **EPSS** | Automatable / likely exploited | **Likelihood** `L ∈ [0,1]` (gates impact) | `VulnIntelPort.epss(cve)` (daily snapshot) |
| **CISA KEV** | Confirmed actively exploited | **Dominant override** — floors the band to RED | `VulnIntelPort.in_kev(cve)` (daily snapshot) |
| **Graph-exposure** | Internet-facing? | **Amplifier** `E` (multiplier) | `AssetExposurePort.exposure(asset_urn)` (cloud_graph read) |

**The shape (illustrative constants — tunable, see D6):**

```
impact I      = cvss_base/10  if a CVSS base score is in attributes, else
                {info:0.1, low:0.3, medium:0.5, high:0.75, critical:1.0}[severity]
likelihood L  = epss                      # probability 0–1 from the daily snapshot
                (no CVE → L = severity-derived prior, so misconfigs still score)
exposure E    = {public:1.0, internal:0.7, private:0.4}[asset.exposure]   # default public if unknown-but-internet-adjacent? NO — default private (least urgency from absence of signal)

blend         = 100 · I · (0.7·L + 0.3) · E      # EPSS gates but never zeroes impact
score         = max(blend, 67) if in_kev else blend     # KEV floors into RED — confirmed exploited outranks predicted
band          = RiskBand.from_score(score)              # reuse the existing 34/67 banding
```

Read the intent, not the arithmetic:

- **KEV dominates.** A KEV CVE is floored into the RED band no matter what CVSS/EPSS/exposure say — you
  are being exploited *now*. (Had the destructive PR-#828-class or any confirmed-exploited CVE been in the
  corpus, it must never be rankable below a private CVSS-critical.)
- **EPSS gates the CVSS-critical-but-unlikely down.** The `(0.7·L + 0.3)` term means a CVSS-9.8 with EPSS
  0.0002 collapses toward the bottom while a CVSS-6.5 with EPSS 0.86 rises — exactly the noise reduction
  BOD 26-04 mandates, without ever zeroing a real finding.
- **Exposure amplifies.** The same CVE on a `public` asset outranks it on a `private` one (`×1.0` vs
  `×0.4`) — reachability is context, per BOD 26-04 question #1.
- **Graceful degradation for non-CVE findings.** The majority of findings are CSPM misconfigs with **no
  CVE** → no EPSS/KEV signal. The scorer falls back to `severity → prior` for `L`, so a *public* misconfig
  still correctly outranks a *private* one. The blend must never produce "unscored" findings.
- **Every score carries its factors.** The job stores the `RiskFactor` breakdown
  (`{key, label, points, detail}`, reusing the existing shape) alongside the number: *"CISA KEV — actively
  exploited (floored to RED); EPSS 0.86 (91st pct); internet-facing (×1.0); CVSS 8.1 base."* The HUD shows
  the *why*, not just the number. This is the explainability William demanded.

### D2 — Threat-intel feeds behind a `VulnIntelPort`, pinned + dated-snapshotted (never live-fetched)

The EPSS + KEV feeds are the same multi-provider, pinned-external-source seam as `ScannerPort` (ADR 0006)
and `LogSourcePort` (ADR 0008), pointed at threat intelligence. A small **`vuln_intel`** context owns:

- **Adapters behind a `VulnFeedPort`** — `EpssFeedAdapter` (pulls the daily CSV,
  `https://epss.empiricalsecurity.com/epss_scores-current.csv.gz`, canonical at first.org/epss;
  fields `cve, epss, percentile`) and `KevFeedAdapter` (pulls
  `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`; fields include
  `cveID`, `dateAdded`, `knownRansomwareCampaignUse`, and a `catalogVersion`).[^epssdata][^kevfeed]
  `httpx` is already in `base.txt` — no new dependency.
- **A Celery **beat** ingestion job** (`vuln_intel.refresh_feeds`, ~daily; EPSS refreshes daily, KEV a few
  times/week) that lands each pull as an **immutable, dated snapshot** — `EpssSnapshot(score_date,
  model_version, …)` rows + `KevSnapshot(catalog_version, fetched_at)` rows — **version-stamped** per
  `pin-versions.md`. The job records the feed's own version (EPSS `score_date`, KEV `catalogVersion`) and,
  ideally, a content checksum. It never overwrites in place, so scoring is reproducible and auditable
  ("scored against EPSS 2026-08-03, KEV catalog v2026.08.01").
- **A read-only `VulnIntelPort`** the scorer consumes (`epss(cve) -> float | None`,
  `in_kev(cve) -> bool`, over the *latest* snapshot). This is a cross-context read-only query (C3) — the
  `findings` scorer never imports `vuln_intel` infrastructure.

The feed data is **reference/enrichment data, not findings** — it does **not** create a per-pillar finding
table (C6). It enriches the one Finding SSOT by CVE id. (Open question O6: `vuln_intel` as a full bounded
context vs. a module — it has its own refresh lifecycle/provenance, which argues BC; noted for review.)

### D3 — Where it lives: a per-finding scorer + materialized table in the `findings` hub, reading exposure + intel by port

Contextual risk is an **enrichment of the Finding SSOT**, so it lives in the `findings` context — the hub,
next to the `WorkspaceAttckCoverage` materialization that already lives there. Respecting ADR 0004's
C-rules:

- **Domain service** `components/findings/domain/services/contextual_risk_scorer.py` — pure, deterministic,
  no LLM, no I/O; takes `(finding, epss, in_kev, exposure)` and returns `RiskScore(value, band, factors)`.
  It **generalizes** the existing `cloud_graph.RiskScoreCalculator` to the per-finding grain (see D5).
- **Materialized table** `FindingRisk` (`infrastructure/persistence/findings/models.py`) — OneToOne to
  `Finding`: `score` (Float 0–100), `band` (RiskBand.value), `factors` (JSON breakdown), `epss`, `epss_pct`,
  `in_kev` (bool), `exposure` (denormalized for display), `scored_at`, feed-version stamps. Index
  `(workspace, -score)` — the read is `ORDER BY score DESC`, mirroring `AttackPath`'s `(workspace, -risk_score)`.
- **Background job** `findings.recompute_finding_risk` (Celery, idempotent recompute-not-increment,
  `soft_time_limit`, `.iterator(chunk_size=500)` per `performance.md`) — recomputes rows for a workspace.
  **Triggers:** (a) on `FindingRaised`/`FindingResolved` (a finding changed → rescore it), and (b) on
  `vuln_intel.refresh_feeds` completion (the daily EPSS/KEV snapshot moved → rescore the workspace, since a
  CVE can *newly* enter KEV or its EPSS can jump without the finding changing). Both are the §6 HARD RULE:
  heavy blend runs in the background, never inline in a request.
- **Cross-context reads by port + URN, never by import (C3/C4):** exposure via an `AssetExposurePort` that
  `cloud_graph` serves, keyed by `AssetUrn` (reusing the exposure read that backs
  `get_exposure_summary_use_case`); EPSS/KEV via `VulnIntelPort`. The scorer correlates by **CVE id**
  (from `attributes`) for intel and by **`AssetUrn`** for exposure — the two shared identities, no FKs.

```
  vuln_intel (feeds)          findings (hub — owns the score)         cloud_graph (owns exposure)
 EpssFeedAdapter ─┐   VulnIntelPort   ┌───────────────────────────┐   AssetExposurePort
 KevFeedAdapter  ─┴──(daily snapshot)▶│ recompute_finding_risk job │◀──(read by AssetUrn)── CloudAsset.exposure
                                      │  → ContextualRiskScorer     │
                                      │  → FindingRisk (materialized)│
                                      └─────────────┬───────────────┘
                                                    │ CQRS Query → DTO
                                                    ▼  ORDER BY score DESC
                                        findings list re-rank  +  Today brief
```

### D4 — Consumption: one ranked read powers both the findings list and the Today brief

The materialized `FindingRisk.score` is the single sort key:

- **Findings list re-rank.** `ListFindingsQuery` gains an `order_by="contextual_risk"` (default) that joins
  `FindingRisk` and orders `-score, -last_seen_at`. `-last_seen_at` stays available as an explicit option.
  Each row exposes `score`, `band`, `epss`, `in_kev`, and the top factors — so the list *shows why* it's
  ranked where it is. This is the seam William's "few that matter" and the wall-of-findings filter hang on.
- **The "Today" brief** (the Tom+William HUD convergence) is a thin CQRS read: **top-N open findings by
  `FindingRisk.score` for the workspace**, grouped by band, each with its one-line factor reason and the
  agent's recommendation. No new aggregation — it reads the same materialized table.
- **"Risk that matters" filter** = `band=red` / `in_kev=true` / `score >= threshold` predicates on the
  same table.

### D5 — Converge the two risk engines; do not fork a third (improve-don't-replicate)

`cloud_graph.RiskScoreCalculator` (per-workspace) and the new per-finding scorer must not become two
divergent risk truths. The per-finding `ContextualRiskScorer` is the **finer-grained primitive**; the
workspace score should become a **rollup of per-finding `FindingRisk` scores** (+ the attack-path
contribution it already folds), replacing its raw open-crit/high/med **counts** with the contextually
scored equivalents over time. This ADR does not rewrite the workspace calculator in one shot, but it
**names the convergence** as the target so we don't ship a third parallel risk formula (`dry-reuse.md`,
`improve-dont-replicate.md`). One risk vocabulary, two grains.

### D6 — Constants live in one tunable module; the model is explainable and versioned

All weights (the EPSS gate `0.7/0.3`, exposure multipliers, the KEV RED floor, any CVSS/severity mapping)
live in **one** module (e.g. `contextual_risk_scorer.py` module-level constants), so tuning is a single
reviewed edit — the same discipline `RiskBand.from_score` already follows. The scorer stamps a
**`model_version`** on every `FindingRisk` row so a blend change is auditable and a re-score is
attributable. FIRST publishes no canonical threshold[^epss] — ours is a **product decision we own and can
defend**, and must be tunable without a schema change.

## Consequences

**Positive:** the findings list and the Today brief finally rank on *risk that matters*, not recency —
directly answering William's "few that matter" and BOD 26-04's four-question model; exposure + confirmed-
exploited + likelihood enter the product as first-class, explainable factors; the noise-reduction that is
the CNAPP thesis (ADR 0004) becomes real because severity is now contextualized; threat-intel feeds arrive
behind the same pinned multi-provider seam as scanners and log sources (one more `Port`, not a new
pipeline); the score is reproducible (dated snapshots) and auditable (factor breakdown + feed-version +
model-version stamps) — which doubles as compliance evidence (ADR 0009).

**Negative / cost:** one net-new small context (`vuln_intel`) with two feed adapters + a beat job + two
snapshot tables; one net-new materialized table + recompute job in `findings`; two cross-context read
ports (`VulnIntelPort`, `AssetExposurePort`). This is deliberate and modest — the alternative (scoring
inline, or ranking on raw CVSS) is the exact debt ADR 0004 §6 and BOD 26-04 exist to prevent.

### Risks & mitigations (with honest residuals)

| Risk | Mitigation | Honest residual |
|---|---|---|
| **Feed outage / staleness stalls triage** | Score against the **last good dated snapshot**; never live-fetch in the request/scan path (D2) | A long EPSS outage means scoring on a stale snapshot — mitigated by the `scored_at`/feed-version stamp surfacing "intel as of <date>". |
| **Feed poisoning / integrity** (a security tool ingesting third-party data) | Pull over HTTPS from the authoritative host; version-stamp + optional checksum; immutable dated snapshots (`pin-versions.md`) | We trust FIRST/CISA as sources; a compromised upstream feed is a supply-chain residual common to all consumers. |
| **Wrong blend weights over/under-rank** | Constants in one tunable module + `model_version` stamp + explainable factors (D6) → tune from real operator feedback | Any fixed weighting is a judgment call; the factor breakdown makes it *arguable*, not opaque — and tunable without a migration. |
| **Missing CVE ↔ EPSS mapping** (GHSA-only advisories, no CVE) | Map by CVE id when present; graceful `severity → prior` fallback so nothing is unscored (D1) | GHSA-without-CVE findings get the prior, not real EPSS — acceptable; revisit if SCA volume makes it material. |
| **Two divergent risk engines** | D5 names the convergence (workspace score becomes a rollup of per-finding scores) | Until the rollup lands, the workspace calculator and per-finding scorer coexist — one grain reconciled over Phase 5. |
| **Recompute cost at scale** | Recompute-not-increment, `chunk_size=500`, event- + feed-triggered (not per-request), indexed read (§6) | A very large workspace's full rescore on every daily feed move has a cost ceiling — bounded by the soft-time-limit + per-workspace scoping. |

## Implementation plan (strangler — each phase ships on its own; this ADR is the spec, design-only)

1. **Threat-intel feed ingestion (`vuln_intel`).** `VulnFeedPort` + `EpssFeedAdapter` + `KevFeedAdapter`;
   `EpssSnapshot`/`KevSnapshot` dated tables; the `vuln_intel.refresh_feeds` beat job (version-stamped,
   immutable). Standalone and immediately inspectable (you can query "is CVE-X in KEV, EPSS?") before any
   scoring exists. **MVP.**
2. **Finding ↔ intel mapping + a read `VulnIntelPort`.** Extract CVE ids from `attributes`; serve
   `epss(cve)` / `in_kev(cve)` over the latest snapshot. Also add numeric **CVSS base** capture to
   `trivy_normalizer` (currently dropped) so `I` can use the real base score, not just the qualitative
   band. **MVP.**
3. **The scorer + materialized `FindingRisk` table + recompute job.** The pure `ContextualRiskScorer`
   (D1) generalizing `RiskScoreCalculator`; `FindingRisk` materialized table; `recompute_finding_risk`
   triggered on `FindingRaised`/`FindingResolved` + feed refresh (D3). Ships the explainable factors.
   **MVP — this is the substrate.**
4. **CQRS read + API.** `order_by="contextual_risk"` on `ListFindingsQuery` (default), the ranked list
   read exposing `score`/`band`/`epss`/`in_kev`/factors, and a `TodayBrief` read (top-N by score). **MVP.**
5. **HUD re-rank + convergence.** Findings list sorts on contextual risk; the Today brief card consumes
   the ranked read; begin the D5 convergence (workspace `RiskScoreCalculator` consumes per-finding
   `FindingRisk` rollup instead of raw counts). **Phase 2 — after the substrate proves out.**
6. **Hardening + tuning.** Per-finding EPSS%/KEV badge display (O5), operator-driven weight tuning, feed
   checksum/integrity, and fitness tests: `vuln_intel` writes only snapshot rows (no finding rows, C6);
   the scorer imports no cross-context infrastructure (C3); `FindingRisk` correlates by CVE/URN, not FK
   (C4). **Phase 2.**

Build only after review. Phases 1–2 are standalone wins (a queryable KEV/EPSS enrichment) even before the
score exists; 3–4 stand up the ranking substrate; 5–6 land the HUD value + converge the risk engines.

## Non-goals

- **Not** a replacement for CVSS/severity — CVSS is the *impact* input, contextualized, not discarded.
- **Not** a live per-request feed fetch — scoring reads dated snapshots only (D2).
- **Not** a black-box / ML risk model — a transparent, tunable, factor-explained function (D1/D6).
- **Not** an auto-remediation trigger — the score *ranks*; acting on it stays the triage agent + sign-off
  (ADR 0010/0012). (Risk-accept-with-reason on a scored finding is a sibling, cheap follow-on.)
- **Not** a new per-pillar finding table — feeds enrich the one Finding SSOT by CVE id (C6).
- **Not** the workspace `RiskScoreCalculator` rewrite — that convergence (D5) is named, staged over Phase 5.

## Open questions / decisions for Henry

1. **Score bands.** Reuse `RiskBand.from_score`'s existing `34/67` GREEN/AMBER/RED cutoffs, or tune for
   this blend? (Reusing keeps one banding across the sign-off spine.)
2. **The blend weights.** Confirm the *shape* (KEV floors to RED; EPSS gates via `0.7·L + 0.3`; exposure
   `1.0/0.7/0.4`) — exact constants are D6-tunable, but the shape is the decision. In particular: should
   **KEV floor to RED, or hard-set to the max score**? And should `knownRansomwareCampaignUse` bump higher
   than plain KEV?
3. **Refresh cadence.** Daily EPSS + KEV pull (proposed). KEV can move intra-day on active exploitation —
   do we want a tighter KEV cadence (e.g. every 6h) than EPSS's daily?
4. **CVSS base capture.** Confirm we start persisting the numeric CVSS base from Trivy (currently dropped)
   so `I` uses the real score — or stay on the qualitative severity mapping for MVP?
5. **Per-finding badges.** Surface **EPSS %** and a **KEV badge** on every finding row/card (recommended —
   it *shows the why*), or only the composite band in MVP?
6. **`vuln_intel` shape.** Full bounded context (own lifecycle/provenance — my lean) vs. a module under an
   existing context?
7. **Exposure default.** When an asset's exposure is *unknown* (not yet in the graph), default to
   `private` (least urgency from absence of signal, proposed) or `public` (fail-safe-loud)?

## Cross-references

- **ADR 0004** — the Finding SSOT + Asset-graph spine; this ADR is its **Phase 6** (the contextual-risk
  materialized table + background job the whole spine was built toward).
- **ADR 0006 / ADR 0008** — `ScannerPort` / `LogSourcePort`: the pinned multi-provider driven-adapter seam
  `VulnFeedPort` mirrors.
- **ADR 0009** — the score's factor breakdown + feed/model-version stamps are audit-grade evidence.
- **ADR 0010 / 0012** — the score *ranks*; the draft-PR loop + Remediation Memory *act* on the top of the
  ranking. Contextual risk feeds triage; triage feeds the fix loop.
- **`cloud_graph`** — owns the exposure signal + the live `RiskScoreCalculator` this generalizes/converges.
- **`.claude/rules/pin-versions.md`** — the feeds are pinned/dated-snapshotted third-party data.
- **`.claude/skills/architecture/SKILL.md` §6** — heavy risk aggregation runs in the background → a
  materialized table → a CQRS read. Non-negotiable, and the spine of D3.

[^bod2604]: CISA — *BOD 26-04: Prioritizing Security Updates Based on Risk* (2026-06-10; the four questions — exposure, KEV, automatable, total-compromise — and the retirement of CVSS-for-prioritization). https://www.cisa.gov/news-events/directives/bod-26-04-prioritizing-security-updates-based-risk
[^picus]: Picus Security — *CVSS Is Officially Dead: What CISA's BOD 26-04 Means for Everyone*. https://www.picussecurity.com/resource/blog/cvss-is-officially-dead-what-cisas-bod-26-04-means-for-everyone
[^zafran]: Zafran — *CISA's BOD 26-04 Signals the End of Patch-Everything*. https://www.zafran.io/resources/cisas-bod-26-04-signals-the-end-of-patch-everything
[^epss]: FIRST — *Exploit Prediction Scoring System (EPSS)* (probability [0–1] of exploitation in 30 days + percentile; FIRST publishes no single canonical threshold). https://www.first.org/epss/
[^epssdata]: FIRST — *EPSS: Get the Data* (daily CSV `cve,epss,percentile`; canonical download, full daily archive back to 2021-04-14). https://www.first.org/epss/data_stats
[^kev]: CISA — *Known Exploited Vulnerabilities Catalog* (authoritative list of CVEs with evidence of active exploitation). https://www.cisa.gov/known-exploited-vulnerabilities-catalog
[^kevfeed]: CISA — *KEV Catalog* JSON feed (`cveID`, `dateAdded`, `knownRansomwareCampaignUse`, `catalogVersion`; versioned JSON schema). https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
[^tiering]: isMalicious — *EPSS vs CVSS vs KEV: How to Prioritize CVEs When Everything Looks Critical* (KEV-first, then EPSS-high + CVSS, tiered thresholds). https://ismalicious.com/posts/epss-cvss-kev-cve-prioritization-security-teams
[^zest]: Zest Security — *Beyond CVSS: Why EPSS and KEV Are Game-Changers for Prioritizing Vulnerabilities*. https://www.zestsecurity.io/blog/beyond-cvss-why-epss-and-kev-are-game-changers-for-prioritizing-vulnerabilities
