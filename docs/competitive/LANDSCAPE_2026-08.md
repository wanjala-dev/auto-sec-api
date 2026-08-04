# Competitive Landscape — August 2026

> **What this is.** A **market-wide** scan of the five segments Auto-Sec touches, and an honest read
> on whether the wedge in `docs/product/STATE_AND_VISION.md` §6 still holds. Companion to
> `docs/competitive/torq-vs-autosec-soc.md`, which is a *single-competitor mechanism teardown* —
> this is the map that teardown sits inside. Reader: the autosec founder.
>
> **Method.** Five parallel research agents, live web search, August 2026. ~40 companies verified
> against funding announcements, pricing pages, and product docs. Segments: AI SOC / autonomous
> triage · down-market developer security · compliance evidence automation · AI security &
> governance · AI-generated-code assurance.
>
> **Confidence note (applies throughout).** Funding figures come from public announcements and are
> reliable. **Revenue, ARR-growth, and customer-count figures are vendor-self-reported** (press
> releases, launch posts) and should be read as positioning, not audited fact. Pricing is public
> where a vendor publishes it and "unknown" where sales-gated — the *absence* of public pricing is
> itself a signal about who a vendor sells to. This is a snapshot of a market consolidating monthly;
> re-ground before betting on any single claim.

---

## 1. TL;DR

- **The space is crowded, but not where Auto-Sec is.** ~$1B went into AI-SOC startups in ~18 months
  and every incumbent now ships a triage agent. **But no pure AI-SOC vendor targets companies with
  no security team at all.** Every one of them terminates in an escalation to a human analyst, which
  presumes an analyst exists.
- **All five segments, researched independently, converged on the same white space:** nobody
  combines (a) cross-layer agentic triage for a SOC-less buyer, (b) draft-PR remediation with
  accumulated fix memory, and (c) provenance-stamped compliance evidence as a byproduct of
  operations. The pieces exist as three products for three buyers.
- **Four real threats**, in order: **Aikido** (owns the buyer, $1B, self-serve pricing that fits),
  **Vanta** (owns compliance for the same buyer and now ships draft remediation PRs), **Datadog Bits
  AI** (closest functional competitor — triage + auto-fix PRs — already inside the target's stack),
  and **the coding agents themselves** absorbing "is my AI code safe" as a free feature.
- **Triage is commoditizing; evidence is not.** The defensible position is *assurance* —
  provenance-stamped evidence derived from real operations. That is architectural, not a feature:
  Vanta can't retrofit it (evidence comes from API pulls), Aikido can't (no ops loop), Datadog can't
  at this price point.
- **The AI-assurance market is forming right now** — EU AI Act high-risk enforcement began
  **2026-08-02**, NIST opened an AI Agent Standards Initiative in Feb 2026, and the AIUC-1
  certification standard has an accredited auditor and a compliance-platform integration. The three
  players nearest "prove your agents acted safely" each hold **one** fragment and none does the
  security work that would generate the evidence.

---

## 2. Segment 1 — AI SOC / autonomous triage

**Verdict: extremely crowded, lavishly funded, and almost entirely aimed at buyers Auto-Sec is not
chasing.**

| Company | Funding | Pricing | Sells to | Proximity |
|---|---|---|---|---|
| Torq (HyperSOC) | $332M total; $140M Series D @ $1.2B (Jan 2026) | Enterprise, unpublished | Large enterprise SOCs | Low |
| Tenex.AI | $250M Series B @ $1B+ (Mar 2026) | Managed-service contracts | Google/Microsoft ecosystem enterprises | Medium |
| 7AI (Seven AI) | $166M; $130M Series A @ ~$700M (Dec 2025) | Enterprise; AWS pay-as-you-go | Enterprise SOCs | Low |
| Exaforce | $200M; $125M Series B @ ~$725M (May 2026) | unknown | Enterprise, incl. cloud-natives (Replit) | Medium |
| Dropzone AI | $57.4M; $37M Series B (Jul 2025) | Was $36K/yr public — **pulled in 2026** | Mid-market 50–1,000 employees | Medium |
| Prophet Security | $41M; strategic round from Amex + Citi Ventures (Feb 2026) | Custom | Enterprise / regulated | Medium |
| Daylight Security | $40M; $33M Series A (Nov 2025) | Managed subscription | Orgs replacing MDR | Medium |
| AirMDR | $15.5M seed (Jul 2025) | **Freemium**; 2–3× cheaper than MDR | **Series A–C, 50–500 employees** | **High** |
| Radiant Security | $15M Series A (2023) | Flat-rate unlimited alerts + **$23/TB logs** | Mid-market to enterprise | Medium |

Plus Intezer, Simbian, Crogl, Qevlar ($30M, Mar 2026), Conifers, Culminate, Salem Cyber — and named
triage agents from CrowdStrike (Charlotte AI), Microsoft (Security Copilot), Palo Alto and Google
SecOps.

**What matters here:**

- **The down-market door is closing, not opening.** Dropzone *removed* its public pricing in 2026 and
  moved to sales-quoted enterprise tiers. Momentum across the segment is toward consolidation and
  MDR-hybridization (AI + human analysts as a service), not product-led security for the unstaffed.
- **AirMDR is the closest ICP collision** — explicitly Series A–C, freemium, "democratization"
  framing. But it assumes **2–5 existing analysts**, and it is a *managed service*: its economics are
  monitoring-hours, not product. No engineering-workflow remediation, no evidence layer.
- **Radiant is worth watching as a counter-example on economics.** It attacks SIEM pricing directly
  ($23/TB log management) — the same anti-ingest instinct as Auto-Sec, but solved by *retaining logs
  cheaply* rather than not retaining them. Ours is the more defensible position for a small buyer;
  theirs is more familiar to a mid-market one.

---

## 3. Segment 2 — Down-market developer security

**Verdict: this is where the actual fight for Auto-Sec's buyer is happening, and Aikido is winning
it.**

| Company | Funding | Pricing | Sells to |
|---|---|---|---|
| **Aikido Security** | **$60M Series B @ $1B (Jan 2026)**; ~$95M total | **$350 / $700 / $1,050 per month, self-serve; free tier** | **Startups with no security staff; 30% discount under $1.5M raised** |
| Oneleet | $33M Series A (Oct 2025); ~$9M ARR | $12K–$60K bundled with pentest + audit | Seed–Series B, first SOC 2; ~⅔ of YC portfolio |
| Nullify | $12.5M seed (Feb 2026) | unknown | Mid-market + high-growth SaaS, thin security staffing |
| Semgrep | $100M Series D (Feb 2025) | Free ≤10 contributors; $35/contributor | Devs bottom-up, enterprise expansion |
| GitHub Code Security | Microsoft | $19–30 per active committer/mo | Any org — **no Enterprise plan required since Apr 2025** |
| Jit | $38.5M seed → **acquired by Torq, May 2026** (~$50–70M) | Was $50/dev/mo flat | *Gone — absorbed upmarket* |
| Wiz (Google) | **Acquired $32B, closed Mar 2026** | $24K/yr entry; SMB bundle is a $222K 36-month contract | Enterprise only |
| Orca / Upwind / Sweet / FortiCNAPP | $250M–$640M each | Sales-gated, $36K–$60K typical | Enterprise |

**What matters here:**

- **The CNAPP tier has structurally abandoned this market.** Wiz post-Google, Orca, Upwind, Sweet and
  FortiCNAPP are all sales-led with entry points far above a Series-A budget. `STATE_AND_VISION.md`
  §6's "priced out of Wiz" premise is **confirmed and strengthening**.
- **But the vacuum got filled by Aikido, not left open.** Aikido is a unicorn selling self-serve at
  $350–$1,050/month to exactly the "no security hire" startup. This is the most important competitive
  fact in this document and it is **absent from the current vision doc.**
- **Aikido's weakness is precise and exploitable:** it is a *scanner aggregator*. No live alert
  triage, no cross-layer production context, no ops loop, no evidence spine. It tells you what's in
  your code; it cannot tell you what happened in your infrastructure at 3am or prove anything to an
  auditor.
- **The two most wedge-shaped independents both left in 2026** — Jit absorbed into Torq's enterprise
  AI SOC, Depthfirst raising $120M in a quarter to chase enterprises. The gravitational pull of this
  market is upmarket, which is *why* the down-market seam stays open for anyone willing to stay in it.

---

## 4. Segment 3 — Compliance evidence automation

**Verdict: crowded and consolidating, and — critically — the compliance side has started building
toward us.**

| Company | Funding | Pricing | Notes |
|---|---|---|---|
| Vanta | $150M Series D @ $4.15B (Jul 2025); **$300M ARR, 16K customers** | ~$10K–$57K/yr; audit extra | **Now opens draft IaC PRs to fix failing cloud tests via MCP / Claude Code plugin** |
| Drata | $328M; ~$100M+ ARR; acquired SafeBase $250M | $10K–$50K+ | Moving upmarket faster than Vanta |
| Oneleet | $33M Series A | $10K–$30K bundled | "Real security, not checkbox" — same buyer as Auto-Sec |
| Sprinto | ~$31.8M | $6K–$30K | Undercuts on price, 3,000+ customers |
| Secureframe | ~$79M | ~$7.5K–$80K | FedRAMP/defense angle |
| Comp AI | $2.6M pre-seed | Open-source self-host + cheap cloud | $1M ARR in 4 months, team of six |
| Delve | $32M Series A @ $300M (2025) | $6K–$15K | **YC delisting, Mar–Apr 2026, over allegedly fabricated AI compliance evidence** |
| AIUC | $15M seed (Nat Friedman/NFDG) | Certification + insurance | AIUC-1 standard; Schellman accredited auditor; Drata first platform integration |

**What matters here:**

- **The Delve scandal is the segment's defining event and it is a direct tailwind for the ADR 0009
  thesis.** Templated fake SOC 2 evidence got a $300M-valuation startup delisted from YC. It
  discredited unverifiable "AI compliance" and made **evidence verifiability the axis of
  competition** — converting Auto-Sec's most abstract design principle into a buyer-visible wound.
- **Vanta is building the compliance→remediation bridge from the other side.** Draft PRs for failing
  control checks, shipping today. It only covers *control-check failures* — never live alerts,
  production incidents, or runtime context — but the direction of travel is unmistakable and the
  vision doc's "Vanta-style aggregator can't match our provenance" claim now needs the qualifier
  *"on provenance — but they are closing on remediation."*
- **Nobody starts from live security operations.** No compliance vendor does deploy-correlated alert
  triage, an ops brief, or remediation with accumulated memory. Their evidence is API pulls and
  screenshots — architecturally incapable of carrying operational provenance.
- **The "second audit" product does not exist.** Every vendor's evidence dies with the subscription.
  Andrei's insight (§2.2 of the vision doc — *first audit you need the platform, second audit why do
  you even need it*) describes a product **no one is building.**

---

## 5. Segment 4 — AI security & governance (the horizon bet)

**Verdict: consolidating at machine speed, entirely at enterprise altitude, and the specific bet
Auto-Sec would make is unoccupied.**

Acquisitions in ~12 months: Protect AI → Palo Alto (~$650–700M, Jul 2025) · Prompt Security →
SentinelOne ($250M, Sep 2025) · Aim → Cato (Sep 2025) · Lakera → Check Point (2025) · Langfuse →
ClickHouse (Jan 2026) · Wiz → Google ($32B, Mar 2026).

Independents raising on "agent security": Noma $100M Series B · **Zenity $125M Series C (announced
2026-08-03)** · Straiker $64M Series A (Jun 2026).

**The three nearest the bet — each holds exactly one fragment:**

| Player | Has | Missing |
|---|---|---|
| **Vorlon** ($15.7M, Accel) | The agent flight recorder | Sells it as enterprise incident forensics; no compliance output, no security work |
| **AIUC** ($15M seed) | The assurance *standard* + audit + insurance | Point-in-time certification with **no operational evidence source** |
| **Agnys** (no disclosed funding) | Hash-chained agent audit logs, $49/mo, self-serve | Records agents without *doing* anything; indie/unfunded |

**What matters here:**

- **Regulatory timing is unusually favorable and unusually current.** EU AI Act high-risk enforcement
  began **2026-08-02** — one day before this document. NIST opened an AI Agent Standards Initiative
  in Feb 2026. "Agent audit trail" language is appearing across roadmaps.
- **The observability layer is not a competitor for this, by framing.** Langfuse, LangSmith, Arize
  and Datadog LLM Observability own the developers but frame everything as *debugging and evals* —
  an engineering tool, not an assurance product with an auditor as the reader. Different buyer,
  different artifact, different retention guarantees.
- **Certifications need exactly the evidence a running triage-and-remediate system generates.**
  AIUC-1 demand is a tailwind, not a threat — it creates buyers for an evidence source it doesn't have.
- **Auto-Sec has an unfair structural claim here:** it is itself a deep-agent system already carrying
  sign-off gates, tool-risk tiers, a kill switch, DeepRun telemetry and an audit trail. The
  dogfooding *is* the proof.

---

## 6. Segment 5 — AI-generated-code assurance

**Verdict: the most crowded cell in security, and the part of the pitch most at risk of being
commoditized to zero.**

- Two unicorns minted in 12 months: **Socket** ($1B, May 2026), **Aikido** ($1B, Jan 2026).
  **CodeRabbit** at $550M doing commodity-priced review at $12–24/contributor.
- **The coding tools are absorbing the check as a feature**: Cursor Bugbot, GitHub Copilot code
  review + Autofix, Replit Security Agent, and **Claude Code's own `/security-review`**.
- **Snyk Evo ADS** (Jun 2026) is the first shipped "govern the coding agents themselves" product —
  first-party-adjacent, enterprise.
- Momentum is visibly fleeing the diff in both directions: upstream to prompt-time policy (Baz
  Planner, Apiiro Guardian) and downstream to runtime validation (Apiiro AI-SAST code-to-runtime,
  Wiz code-to-cloud) — but the downstream motion exists **only as enterprise ASPM/CNAPP features
  that presume a security team to operate them.**

**The hard implication for positioning.** Tom's line — *"writing code isn't the problem; how do I
know I'm shipping safely?"* — is a **true statement of pain but a dangerous product center of
gravity**, because Anthropic, Microsoft and Cursor ship part of that answer for free inside the
editor. The durable version of that promise is not "review my diff." It is **"connect what I shipped
to what is now happening in production, and prove it."** Deploy correlation, blast radius, and
evidence — none of which a PR-review tool can do, and none of which the enterprise players who *can*
do it will sell to a Series-A team.

---

## 7. The converged white space

Five independent segment scans produced the same negative result. Stated positively, the unoccupied
position is:

> **Do the security work for a company with no security staff, and let audit-grade evidence
> accumulate as the byproduct.**

Concretely, nobody does all three:

1. **Cross-layer agentic triage for a SOC-less buyer** — every triage vendor terminates in an
   escalation to a human security analyst rather than a deploy-correlated engineering brief.
2. **Remediation as draft PRs with vetted-fix memory** — this loop exists only in AppSec tools
   (Aikido, Corgea, ZeroPath) that do no runtime or alert triage.
3. **Provenance-stamped evidence as an operational byproduct** — Culminate's "attestable reports" and
   Crogl's compliance messaging are the closest, both enterprise-facing; TestifySec is evidence-first
   but aims at regulated supply chains, not startup audits.

Two further positions are entirely empty: the **anti-ingest economics stance** (ephemeral scans,
windowed reads, no log retention — Radiant is moving the *opposite* way at $23/TB), and **independent
third-party assurance of AI coding agents** (the coding vendors auditing their own output have a
structural conflict an independent layer does not).

---

## 8. What this changes in `docs/product/STATE_AND_VISION.md`

That doc is dated 2026-07-31. This research **confirms its core wedge** and **invalidates or updates
several specifics**.

**Confirmed:**

- "Priced out of Wiz" — strengthened. Wiz's SMB bundle is now a $222K 36-month contract.
- "Can't adopt Dropzone (assumes an existing SIEM/SOC)" — confirmed, and Dropzone has since moved
  further upmarket.
- The compliance lens (§6, ADR 0009) — **the strongest finding in this research.** The Delve scandal
  made provenance a competitive axis, and no compliance vendor can produce operations-derived
  evidence.
- §9's open question *"does the wedge match the interviews?"* — Tom validated the framing verbatim
  and unprompted; the market data confirms the SOC-less buyer is served by nobody in the AI-SOC cohort.

**Stale or missing — worth updating in the next revision of that doc:**

1. **§2 funding figures are out of date.** "Dropzone $37M, Prophet $30M" → Dropzone $57.4M, Prophet
   $41M, plus an entire new cohort (Torq $140M @ $1.2B, Tenex $250M @ $1B+, Exaforce $125M @ $725M,
   7AI $130M @ $700M).
2. **Aikido is absent entirely** — and it is the single most direct competitor for the stated wedge.
3. **"A Vanta-style aggregator can't match our provenance"** needs qualifying: still true on
   provenance, but Vanta now ships draft remediation PRs.
4. **Datadog Bits AI is unmentioned** — autonomous triage + auto-fix PRs, already inside the target
   customer's stack. The closest functional competitor in existence.
5. **The AI-assurance horizon bet is missing from §6** — and the regulatory clock started 2026-08-02.
6. **"CNAPP-without-analyst vs analyst-without-graph"** remains accurate but is no longer the
   sharpest framing. The sharper one is **work-without-evidence vs evidence-without-work.**

---

## 9. Founder takeaway

- **Do not lead with "AI SOC."** It is a $1B, forty-competitor race against companies with
  enterprise sales machines, and the category's own momentum is away from this buyer. Triage is a
  *capability* Auto-Sec has, not the *position* it should claim.
- **Lead with assurance.** "Do the work, and prove it" is defensible because it is architectural.
  Vanta cannot retrofit operational provenance; Aikido has no ops loop; Datadog cannot reach the
  price point. Everything else built should feed that spine.
- **Watch Aikido specifically.** If they add live triage plus an evidence layer, they arrive with the
  buyer relationship already in hand. Their scanner-aggregator architecture is the reason they
  haven't — that is the head start, and it is measured in quarters, not years.
- **Treat the AI-agent audit bet as real but unbuilt.** Write it down, do not build it yet. The
  standards are being written now; the evidence spine built for human-facing compliance is the same
  spine that serves it later.
- **The market map cannot decide whether to continue.** It says the space is survivable and the seam
  is genuinely open — more than most pre-launch founders get. What decides it is whether the design
  partner opens the product again the week after the first real deployment. Crowded markets kill
  founders who build in a vacuum; a funded design partner who volunteered unprompted is worth more
  than any funding round in the tables above.

---

## 10. Sources

Research conducted 2026-08-03 via five parallel web-search agents. Funding figures from public
announcements (Crunchbase, TechCrunch, company press releases); pricing from vendor pricing pages
where public. Revenue, ARR-growth and customer counts are **vendor-self-reported**. Key events
referenced: EU AI Act high-risk enforcement (2026-08-02), NIST AI Agent Standards Initiative (Feb
2026), Delve YC delisting (Mar–Apr 2026), Wiz/Google close (Mar 2026), Jit/Torq acquisition (May
2026), Zenity Series C (2026-08-03).

Companion documents:

- `docs/competitive/torq-vs-autosec-soc.md` — single-competitor mechanism teardown (the SOC benchmark)
- `docs/product/STATE_AND_VISION.md` — product state + north star (see §8 above for deltas)
- `docs/adr/0009-compliance-lens-audit-grade-evidence.md` — the evidence/provenance decision this
  research most strongly validates
