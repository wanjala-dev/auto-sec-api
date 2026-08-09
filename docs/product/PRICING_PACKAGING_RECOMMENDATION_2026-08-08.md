# Auto-Sec Pricing & Packaging — Free / Pro / Premium (research-grounded, 2026-08-08)

Decision document answering Henry's question: *"what should be paid vs free?"*
Inputs: 4 research sweeps (unit costs from this repo, CNAPP market, AI-SOC/code-fix/compliance
anchors, packaging theory), 3 candidate packages, 3 adversarial judgments (margin / ICP / position).
Verified in-repo today: `components/shared_platform/application/config/tier_features.py:32-41`,
`components/subscription/domain/entitlements.py:149-165`,
`components/subscription/application/config/plan_catalog.py:24-28`,
`components/shared_platform/cli/management/commands/seed_feature_flags.py:27-136`.

---

## 1. The recommendation, in one paragraph

**Meter on connected estate — cloud accounts, repos, container images — never on seats, never per
finding, never per draft PR.** Ship a usage-limited free tier that reaches the whole differentiator
on a small estate (1 cloud account, 1 repo, 3 images, weekly scans, 15 AI actions/month), a single
self-serve paid tier at **$249/month** (3 accounts, 25 repos, 50 images, continuous scanning, 250 AI
actions, unlimited seats, +$79/extra cloud account), and a **$899/month** Premium that we define in
code now but **do not market until it has capabilities Pro doesn't** (provenance drill + compliance
evidence are partial/dark today — selling them would be selling vapor). The logic in one sentence:
**we give away everything whose marginal cost is near zero — the graph, the attack paths, the
correlated finding, EPSS/KEV, ATT&CK, the board, the deterministic fix advice — and we charge for
scale of estate and freshness of scanning, because those are the only two things that cost us real
money per customer and the only two things that grow with the customer's value.**

The corollary that surprises: **`_PRO_FEATURES` being empty is closer to correct than any of the
three packages assumed.** The four scanner flags (`cloud_posture`, `cloud_asset_graph`,
`container_security`, `code_security`) should be *Free*, not Pro. With today's flag set the Free→Pro
difference is almost entirely quantitative — which means the blocking work is **a quota layer that
does not exist**, not a bigger frozenset.

---

## 2. The literal answer to the blocking question

### 2.1 The frozensets

```python
# components/shared_platform/application/config/tier_features.py
#
# The plan-tier layer sits at:  user rule → workspace rule → PLAN TIER → global → default
# It can only turn a flag ON. Free is therefore NOT empty: the four scanner flags are
# globally-disabled in prod (seed_feature_flags.PROD_DISABLED_FLAGS), so the Free tier's
# set is what actually makes the wedge reachable without a card.

# Free is the acquisition surface. Every key here is capability the customer gets at $0 —
# bounded by QUOTA (accounts/repos/images/cadence/AI actions), not by amputation.
_FREE_FEATURES: frozenset[str] = frozenset(
    {
        "feature.cloud_posture",       # Prowler CSPM — 1 account, weekly
        "feature.cloud_asset_graph",   # the graph + attack paths — the wedge, zero marginal cost
        "feature.container_security",  # Trivy + SBOM — 3 images, weekly
        "feature.code_security",       # Opengrep SAST → AI fix → draft PR — 1 repo, weekly
    }
)

# Pro adds capability that costs real money per use or only compounds with volume.
# NOTE: all three keys below MUST BE MINTED (see §2.3) — none exists today.
_PRO_FEATURES: frozenset[str] = _FREE_FEATURES | frozenset(
    {
        "feature.scheduled_reports",    # MINT — PDF exec/pentest report + scheduled delivery
        "feature.remediation_memory",   # MINT — per-tenant retrieved fix KB at triage time
        "feature.finding_history",      # MINT — trend/history beyond the Free retention window
    }
)

_PREMIUM_FEATURES: frozenset[str] = _PRO_FEATURES | frozenset(
    {
        "feature.provenance_graph",     # exists; inert until the drill ships (task #93)
        "feature.compliance_evidence",  # MINT when ADR 0009 builds — dark today
        "feature.sso_saml",             # MINT when built — not built
    }
)

TIER_FEATURE_MAP: dict[str, frozenset[str]] = {
    "Free": _FREE_FEATURES,
    "Pro": _PRO_FEATURES,
    "Premium": _PREMIUM_FEATURES,
}
```

**Deliberately absent from every tier — and this is a correction to all three candidate packages:**

| Flag | Why it must never be in the tier map |
|---|---|
| `feature.ai_kill_switch` | Operator break-glass. Gating safety on a plan is indefensible for a security product, and no CNAPP in the market sweep paywalls a kill switch. |
| `feature.support_impersonation` | Staff escalation, per-user rule only. Not a product capability. |
| `feature.logwatch_board_from_findings` | **Not a sellable capability — an internal reversible cutover switch** (ADR 0004, "flipped once dual-write parity is observed", per its own seed description). Tier-gating it would give paying customers a *different board write path* than free ones. That is a correctness hazard dressed as packaging. Packages A, B and C all got this wrong. |
| `feature.log_source_cloudwatch` | **An adapter-registration flag, `default_enabled=True`, not in `PROD_DISABLED_FLAGS`** — i.e. already on for everyone. Tier-gating it would (a) retract a shipped capability and (b) mean an **ACTIVE CloudWatch source silently stops being read when a plan lapses** — a data-loss-shaped failure in a security tool. Meter log ingestion by GB quota instead. |
| `feature.sample_data_mode` | A trial lever the owner/operator sets (ADR 0011), the demo-mode SSOT. Not an entitlement — putting it in a tier makes "show me demo data" a purchase. |
| `dev_tools` | Internal. |

### 2.2 Capability → tier → rationale (including the not-yet-flagged)

| Capability | Flag today | Tier | Marginal cost | Rationale |
|---|---|---|---|---|
| Findings SSOT, board/kanban, tagging | none | **Free** | ~0 (DB) | Seeing your own findings is table stakes everywhere in the market. |
| Cloud asset graph + attack paths | `feature.cloud_asset_graph` | **Free** | ~0 (rides Prowler inventory; correlation is deterministic) | **This is the wedge and it is fixed-cost.** Cloudflare gave away unmetered DDoS because the network was already built. Same test, same answer. |
| Cloud posture / CSPM | `feature.cloud_posture` | **Free** (1 acct, weekly) | Prowler Job: 4Gi × ≤30 min | Prowler OSS is free and unlimited; charging for "we ran Prowler" is charging for a complement someone else gives away. We charge for *accounts × freshness*. |
| Container scan + SBOM | `feature.container_security` | **Free** (3 images, weekly) | Trivy Job ≤20 min + SBOM object | Trivy has **no paid tier at all** upstream. Same logic. |
| Code security (SAST → AI fix → draft PR) | `feature.code_security` | **Free** (1 repo, weekly, inside the AI-action cap) | Opengrep Job ≤15 min + 1–2 advisor calls | **The single change I make to the leading package.** Tom's wedge moment is a real fix PR on his real repo, not a graph. Semgrep gives its full cloud platform free to 10 contributors/10 repos; a 1-repo free lane is *less* generous than the market leader's and costs <$0.50/workspace/month. |
| **AI triage / advisor (the analyst)** | none | **Free, quota-limited** | $0 for attack-path + container (deterministic, no LLM); $0.05–$0.15/action for SAST + log | Never mint a boolean here. No AI-SOC vendor sells a "lite analyst"; the category meters *capacity*, and a degraded analyst is not a product. Quota, not capability. |
| **Guardrailed draft-PR remediation** | none | **Free, quota-limited** | patch advisor ≤4000 out tokens + full-file input | Same reason. Also: charging per fix is the documented perverse incentive ("pay more to confirm your fixes work"). |
| **Response actions + sign-off (reversible)** | none | **Free, every tier** | ~0 (boto3, dry-run default) | Charging for the ability to *act on* a finding we showed you is the same perverse incentive one step later. This is also the "consequence" half of the judgment-enforcement thesis — paywalling it guts the positioning. |
| Contextual risk (EPSS / KEV / exposure) | none | **Free** | ~0 — free public feeds, one platform-wide daily refresh amortized across all tenants | Commodity. Gating it signals we don't know the market. |
| MITRE ATT&CK coverage | none | **Free** | ~0 (materialized `WorkspaceAttckCoverage`) | Commodity. |
| Slack / notification delivery | none | **Free** | ~0 (webhook) | William's "one actionable digest" *is* the delivery. Gating the digest gates the value. |
| Seats / RBAC / audit trail / sign-off / recycle bin / MFA | none | **Free, unlimited, every tier** | 0 | Non-negotiable (§3). Unlimited seats is a feature, not a concession — "the security team you don't hire" cannot be priced per head. |
| Multi-source log ingest (S3 / CloudWatch) | `feature.log_source_cloudwatch` (adapter reg.) | **Free capability, GB-quota'd** | S3/CW GETs + LLM advisor per error finding | William explicitly named ingest cost control. Meter GB, never gate the source type. |
| **PDF exec / pentest report** | none — **MINT `feature.scheduled_reports`** | **Pro** | deterministic assembler + **2 narrative LLM calls + 1 faithfulness retry** + Gotenberg render + PDF object | Real per-use cost, and "history, trending, reporting" is on the market's expected-to-be-paid list. |
| **Remediation Memory** (per-tenant fix KB) | none — **MINT `feature.remediation_memory`** | **Pro** | low — one `text-embedding-3-small` per captured fix | Near-zero cost, so §3's test says give it away — but it *demonstrates nothing on day one*; it compounds. Gating it costs no discovery. This is the one deliberate exception to the give-away-fixed-cost rule, and I name it as such. |
| **Finding history / trend beyond retention** | none — **MINT `feature.finding_history`** | **Pro** (Free = 30d, Pro = 1y, Premium = unlimited) | storage | History + trending is universally paid. Costs real bytes. Honest axis. |
| Provenance & access graph | `feature.provenance_graph` | **Premium** | 0 | Exists but partial (drill unbuilt, task #93). Listing it is inert until the flag's surface ships — the resolver no-ops on a flag whose row/surface doesn't exist. |
| **Compliance lens + evidence envelope** | none — **MINT `feature.compliance_evidence`** when ADR 0009 builds | **Premium** | TBD | **DARK today** — there is no `components/compliance`; only Prowler's compliance map passes through. Do not price it before it exists. |
| **SSO / SAML** | none — **MINT `feature.sso_saml`** when built | **Premium** | 0 | Classic, universally-accepted paid line. Not built. |
| Sample/demo data | `feature.sample_data_mode` | **not a tier entitlement** | 0 | Trial lever (ADR 0011), operator-set. |
| Kill switch / impersonation / dev tools | `feature.ai_kill_switch`, `feature.support_impersonation`, `dev_tools` | **never** | 0 | Safety + staff. |

### 2.3 New flag keys that must be minted

`feature.scheduled_reports` (Pro, mint now — the capability exists), `feature.remediation_memory`
(Pro, mint now — P3–P6 shipped), `feature.finding_history` (Pro, mint with the retention quota),
`feature.compliance_evidence` (Premium, mint **when ADR 0009 builds**),
`feature.sso_saml` (Premium, mint **when built**).

**Do not mint** `feature.ai_triage`, `feature.draft_pr`, `feature.response_actions`,
`feature.attack_paths`, `feature.contextual_risk`, `feature.mitre_coverage`. Each of those is either
the wedge (gate it and nobody discovers the differentiator) or commodity (gate it and we look like
we don't know the market). They are quota-governed or free, not flagged.

---

## 3. What is free forever, and why

**Non-negotiable (safety / integrity).** `feature.ai_kill_switch`, RBAC + capability gating, the
immutable audit trail, sign-off approvals, recycle-bin tombstoning, MFA/OTP/session controls, account
lockout. Gating a break-glass or an audit trail behind a plan is indefensible for a security product,
it converts a lapsed subscription into a security incident, and the market sweep found **zero** CNAPP
vendors who paywall either. Unlimited seats belongs in this bucket for a different reason: William's
escalation team must all see the digest, and per-seat pricing directly contradicts what we sell.

**Strategic free — the test is marginal cost, not differentiation.** The cloud asset graph, the
attack-path correlation and its deterministic remediation advice, EPSS/KEV contextual risk, ATT&CK
coverage, the findings SSOT + board + tagging, response actions (dry-run default), and Slack
delivery. Every one is either a materialized table, a free public feed refreshed once
platform-wide, or a documented **zero-LLM** advisor
(`AttackPathRemediationAdvisor`: *"Deterministic on purpose (no LLM)"*;
`ContainerVulnRemediationAdvisor`: *"Deterministic (no LLM) — Trivy already told us the fixed
version"*; `finding_verifier`: *"verifies deterministically — zero LLM"*).

This is the whole argument, so state it plainly: **the wedge sentence — "this handler has no authz
check *and* it is internet-reachable via this IAM path" — is produced by deterministic code and costs
us nothing to serve.** Constraint #3 (don't gate the wedge) is satisfied by cost structure, not
charity. Cloudflare freed unmetered DDoS mitigation because the network was already built; Google cut
Gemini free-tier quotas 50–92% because inference isn't. Giving away the graph is Cloudflare-shaped.
Giving away unlimited agent runs is Gemini-shaped. We do the first and never the second.

**Free *engine output*, specifically.** Prowler OSS is unlimited and free, Trivy has no paid tier at
all, Opengrep/Semgrep OSS is free. A prospect verifies that in ten seconds. We cannot charge for
"we ran the scanner". We charge for the **correlation across engines, the freshness of the run, and
the scale of the estate** — the operational labour a self-hoster would have to do themselves.

---

## 4. Unit economics

### 4.1 Per-unit inputs (derived, with the honest error bars)

Priced against the seeded catalog (`seed_ai_models.py`): default `gpt-4o` at **$0.0025/1k in,
$0.01/1k out**.

| Unit | Plan figure | Stress figure | Derivation |
|---|---|---|---|
| **AI action** (one LLM-backed advisor outcome that survives the groundedness gate) | **$0.15** | **$0.30** | SAST advisor ≤900 out = $0.009, ×2 for the one groundedness re-advise (`_finding_processing.py:159-183`) = $0.018; full-file input 4–12k tok = $0.010–$0.030; amortized deep-run planner/critic/synthesizer (batched over a 240s dispatch lease) = $0.02–$0.05; patch advisor ≤4000 out = $0.040 + input. Midpoint ≈ $0.06–$0.10 → plan at ~2× = $0.15. Stress = a monorepo user with 5–10× input. |
| **Scan job** | **$0.05** | **$0.12** | Prowler 4Gi × ≤30 min (2Gi OOMKills a real account scan); Trivy 2Gi × ≤20 min; Opengrep 2Gi × ≤15 min; requests 250m CPU / 256Mi, `ttlSecondsAfterFinished=600`. **Node $/hr is NOT in this repo — it lives in `auto-sec-infra`. Both figures are assumptions and must be replaced.** |
| **Platform allocation** | $2/free ws, $8/Pro, $25/Premium | +25% | Postgres/pgvector share, Redis, SBOM + PDF objects in MinIO, log GETs. Estimate. |
| Attack-path / container triage | **$0.00** | $0.00 | Deterministic advisors — verified in code. |
| Embedding (captured fix) | rounding error | — | `text-embedding-3-small`. |

**Two caveats that belong in the ADR, not a footnote.** (1) The model catalog is a *seeded* price
list, not a live feed — a provider price change is invisible until `seed_ai_models` is re-run, which
silently moves the margin floor. (2) `costing.py::cost_usd_for_tokens` returns `None` rather than
fabricating $0 for an unpriced model, and run-total rollups skip those records — **our meter
under-reports by construction** until the catalog is complete. Any dollar ceiling built on it leaks.

### 4.2 The tiers, with limits stated as part of the tier

| | **Free — $0** | **Pro — $249/mo** ($2,490/yr, −17%) | **Premium — $899/mo** ($8,990/yr) — *defined, not yet marketed* |
|---|---|---|---|
| Who | Solo builder / evaluating founder | **Tom** — founder shipping daily with AI-written code | **William** — infra/security manager, multi-account |
| Cloud accounts | 1 | 3 (**+$79/mo each**) | 10 |
| Repos | 1 | 25 (+$49/mo per 25) | 100 |
| Container images | 3 | 50 | 250 |
| Scan cadence | **weekly** | continuous — daily CSPM, per-push SAST (6h/repo cooldown), image rescan on digest change | continuous + on-demand |
| **AI actions/mo** | **15** | **250** (+250 one-time onboarding grant, first 30 days) | **750** |
| Log ingest | 1 GB/mo | 25 GB/mo | 150 GB/mo |
| Finding retention | 30 days | 1 year | unlimited |
| Seats | **unlimited** | **unlimited** | **unlimited** |
| At the ceiling | **soft throttle** — critical-severity only, never a hard stop | soft throttle | soft throttle |
| Overage invoice | **none, ever** | **none on AI** — expansion is sold as fixed per-unit add-ons | none |

**Dormancy throttle (load-bearing, not a detail):** a Free workspace with no login for 14 days drops
to monthly scans and a zero AI-action queue until someone signs in. §4.3 explains why this is what
makes the free tier survivable.

### 4.3 The arithmetic, including the abuse case

**Free, fully burned (the abuse case):** 15 × $0.30 = $4.50 AI; weekly cycles = 4 × (1 CSPM + 1 SAST
+ 3 images) = 20 scans × $0.12 = $2.40; platform $2. **= $8.90/workspace/month, hard-bounded.** At
plan figures: $2.25 + $1.00 + $2 = **$5.25**. Median free user (1 account, never touches the AI cap,
goes dormant in week 3) ≈ **$1.50–$2.50**.

**The constraint nobody in the three packages did honestly:** median B2B freemium conversion is
**2.6% lifetime**, so ~38 free workspaces exist per paid one — *permanently*, not once. At $6/free
workspace that is **$228/month of recurring free COGS against $249 of Pro revenue** — a break-even
business. At $2.50 (dormancy-throttled) it is $95, which clears. **The dormancy throttle is not a
nicety; it is the difference between a free tier that funds growth and one that eats it.** State the
rule out loud: *free-tier COGS must stay under ~$3/workspace/month averaged across the cohort.*

**Pro at $249, allowance fully burned:**
- Plan: AI 250 × $0.15 = $37.50; scans (3 accts × 30 CSPM = 90) + (25 repos × ~8 pushes = 200 SAST) +
  (50 images × 4 = 200) = 490 × $0.05 = $24.50; logs $2; platform $8. **COGS $72 → 71% GM.**
- AI 2× stress only: $75 + $24.50 + $2 + $8 = **$109.50 → 56% GM.**
- Scan 2.4× stress only: $37.50 + $59 + $2 + $8 = **$106.50 → 57% GM.**
- **Compound stress (both wrong at once): $148 → 41% GM.** This is a **repricing trigger**, not a
  design point — and telemetry surfaces it before customers do.

**Premium at $899, allowance fully burned:**
- Plan: AI 750 × $0.15 = $112.50; scans (300 CSPM + 800 SAST + 1000 image) = 2100 × $0.05 = $105;
  logs $12; platform $25. **COGS $254.50 → 72% GM.**
- AI 2×: $367 → **59%.** Scan 2.4×: $401.50 → **55%.** Compound: $531 → **41%** (repricing trigger).

**Pricing floor rule, stated as policy:** *never sell at a price where a 2× miss on the single
dominant cost line breaches 50% gross margin.* Both tiers clear it. Both AI-native benchmarks —
ICONIQ's 52% median AI gross margin, the 50% target median in Poyar's survey — sit below where we
land, and the 60–70% band public AI companies now defend is our plan case.

**Note which cost dominates.** At Premium, **scan-job compute is the largest line, not the LLM** —
2100 jobs/month at an unknown node rate. That is the number I am least sure of and the one most
capable of inverting the whole model. It lives in `auto-sec-infra`, not here.

---

## 5. The market evidence, and where we sit deliberately

**Nobody in enterprise CNAPP publishes a price.** `wiz.io/pricing` (fetched 2026-08-08) lists five
SKUs and zero dollar figures; its only pricing statement is the metric — *"Licensing is modular —
scaling with your workloads, active developers, log ingestion, or sensors."* Orca, Sysdig, Upwind,
Prisma Cloud, FortiCNAPP: all contact-sales. Third-party estimates put Wiz at ~$24k/yr per 100
workloads and a median ACV near $149k; Orca ~$6.5k per 50 workloads; Prisma on credits (~$1.20 list);
FortiCNAPP's AWS Marketplace starter pack at **$22,000/yr**. **"Contact sales" is itself the finding**
— that motion needs a sales team Henry does not have.

**The metric has converged and it is not seats and not findings.** Every enterprise CNAPP charges on
estate size — workload, host, resource, credit, cloud account. Only 5% of surveyed investors back
seat-based for AI products. And **the one vendor that publicly priced per unit of AI work retreated**:
Dropzone AI listed ~$36k/yr for 4,000 investigations (~$9 each), then **pulled all public prices in
2026**. The prevailing trade argument is now explicit — a meter "charges you more precisely when it's
working hardest", and finding-count economics reward *"volume, not relevance"*, so *"a tool that
reports fewer findings because it understands context looks weak next to one that floods the page."*
Auto-Sec's entire product claim is noise reduction. **A per-finding or per-PR meter would make our
core value proposition revenue-negative.** That is why we never invoice a meter.

**What buyers already expect free:** the scanner engine (Prowler OSS, Trivy, Semgrep OSS — all
unlimited); a small-estate self-serve tier with no card (Aikido Developer: 1 cloud account, 10 repos,
2 images, 10 AI AutoFixes/mo, scans every 3 days; Semgrep: full cloud platform free to 10
contributors/10 private repos); seeing your own findings; and safety/RBAC/audit.

**What they expect paid:** estate scale; **scan freshness** (Aikido's 3-day-free vs continuous-paid is
the cleanest cost throttle in the market and we copy it); history and trending; unlimited AI fixes;
SSO/data residency; support. Note Aikido meters AI AutoFixes on free (10/mo) and unlimited on paid —
**the AI meter is an industry-normal free-tier cost guard, never a revenue metric.** That is exactly
our design.

**Where the fix is bundled, not sold separately.** GitHub unbundled GHAS into Secret Protection
$19/committer/mo and **Code Security $30/committer/mo with Copilot Autofix inside it**. Semgrep Team
$35/contributor bundles the AI Assistant. Snyk Team $25/contributing-dev bundles everything. The only
vendor selling "resolutions" as the unit is **Pixee** — *"Security tools charge for seats while
vulnerabilities pile up. Pixee charges for resolution."* — and Pixee can do that **precisely because
it does not own the finding**; it consumes someone else's SARIF. We own both, so that shape isn't
available to us.

**Our deliberate position.** Pro at **$249** sits below Aikido Basic ($300) with a comparable estate,
and above Prowler Cloud's published **$99/cloud-account/mo** ($79 annual, then $0.30/resource
overage) — so a prospect comparing us to the single-engine incumbent sees more product for ~2.5×,
and a prospect comparing us to the transparent multi-engine incumbent sees a lower entry. Premium at
**$899 (~$10.8k/yr)** sits at the Vanta compliance floor (~$10k/yr single-framework under 50
employees) and roughly half of FortiCNAPP's Marketplace entry — but we **do not list it until
provenance and compliance actually ship**. Free is deliberately more generous than Prowler Cloud's
free tier (one scan, one account) and slightly *less* generous than Aikido Developer on counts — but
uniquely includes the graph correlation, which neither sells at any price.

**And we publish the numbers.** The incumbents' silence is the wedge: a solo founder cannot win a
contact-sales fight and shouldn't try. Snyk publishes ~$25/dev and built 4.5M developer users
bottom-up.

---

## 6. Where the judges disagreed — and who I find more credible

**Disagreement 1 — which package wins.** Margin ranked C > B > A and scored A **4/10**. ICP ranked
A > B > C. Position ranked A > C > B. Two of three lead with A, and reading the margin critique
closely, **it is an attack on A's numbers, not A's shape**: $199 with 500 AI actions is the cheapest
price with the highest allowance (2.51 actions per revenue dollar vs C's 1.20), and A's free-tier
estimate omitted platform overhead entirely ($3.05 claimed vs C's $8 for a functionally identical
tier). **I side with ICP + position on shape and with margin on arithmetic** — hence A's structure at
C's price ($249, not $199) with a smaller allowance (250, not 500), the dormancy throttle, and the
input-context cap. Margin's ranking of A last does not survive the correction of A's inputs.

**Disagreement 2 — meter the AI as revenue?** Margin liked C's $0.50 overage precisely because it
makes heavy users *more* profitable (70% margin on overage). ICP and position killed it: it makes
William ration the digest he asked for, it re-creates the incentive the buyer literature names as the
category's cardinal sin, and Dropzone publicly retreated from that exact metric in 2026.
**I side against the revenue meter** — but margin's underlying concern is real and I fix it on the
**cost side instead of the price side**: cap the input context per advisor call and enforce a
workspace-month cost ceiling on the existing `ExecutionBudget` rail. That removes the variance that
makes an action cost $0.45 instead of $0.15, without ever putting a meter on an invoice. Margin's own
"single highest-leverage change" was exactly this, so the disagreement resolves rather than splits.

**Disagreement 3 — is the wedge actually free?** Margin and position said yes (fixed-cost graph).
ICP said the graph wedge is free but **Tom's** wedge — a real fix PR on his real code — is behind
`feature.code_security` in both A and C, so *the free path in the leading package does not reach the
moment that converts anyone*. **I side entirely with ICP.** This is the single change I make, and the
cost of making it is under $0.50/free workspace/month. Three operator interviews and Tom's own ranked
#1 gap (remediation → IaC/Terraform PR) all point the same way; the graph converts William, and
William is not who arrives at a $0 signup form.

**Where all three agreed (so I treat it as settled):** estate as the metric; never seats; never per
finding or per PR; scan freshness as the throttle; safety/RBAC/audit/EPSS/ATT&CK never gated; publish
the price; **and `TIER_FEATURE_MAP` is not the entitlement layer** — the frozensets are at most half
the answer.

---

## 7. The biggest risk, and the leading indicator that this is wrong

**The risk: we are giving away the wedge before the wedge is reliable.** Free now includes
SAST → AI fix → draft PR on one repo. `docs`/task #117 — *"SAST fix quality: rule-specific fix
templates (BEFORE pointing at Tom's repo)"* — is still open. If the fix quality is poor, a free user's
first experience of the differentiator is a PR they close without reading, and free acquisition
becomes **negative** marketing at scale, paid for by us. This risk is deliberately accepted because
the alternative (ICP judge, correctly) is a free tier nobody converts from — but it is the thing most
likely to break.

**The leading indicator: draft-PR merge rate on free workspaces (merged ÷ opened, 30-day trailing).**
This is measurable *today* — PR-merge detection already ships as part of Remediation Memory P4a.
**If it sits below 30%, pull `feature.code_security` out of `_FREE_FEATURES` and fix quality first.**
Secondary indicators: free-workspace COGS trending above $3/month averaged across the cohort (the
dormancy throttle isn't working); a majority of Pro workspaces hitting the 250-action soft throttle
(the allowance is wrong, or the router is dispatching LLM advisors too eagerly); and observed
cost-per-action landing above $0.25 (the input cap isn't holding).

**Second risk, named honestly: the funnel is slow.** Snyk's self-serve paywall took ~2 years and
~50k registrations to reach $100k ARR; median freemium conversion is 2.6%. This is a compounding bet,
not a revenue plan for this quarter. If Henry needs revenue sooner, Package B's trial-only shape
converts faster from a smaller top of funnel — and that is a legitimate different bet, not a worse
one. It is his call, not this document's (§8).

---

## 8. What Henry decides vs what this document decides

**This document decides (grounded, and I'd defend each):**
1. The value metric: **connected estate** (cloud accounts + repos + images), never seats, never
   per-finding, never per-draft-PR, never tokens or credits.
2. Safety, RBAC, audit, sign-off, kill switch, unlimited seats are free at every tier, permanently.
3. The four scanner flags belong in **Free**, not Pro — the wedge is fixed-cost.
4. `feature.logwatch_board_from_findings` and `feature.log_source_cloudwatch` are **not sellable
   flags** and must be kept out of the tier map (§2.1) — this is a correctness finding, not a
   pricing preference.
5. `feature.sample_data_mode` is a trial lever, not an entitlement.
6. **Premium's `{}` in `TIER_CATALOG` — which today grants unlimited AI runs — must be closed.**
   Unlimited AI on any tier is the Gemini-free-tier bankruptcy pattern with a price tag on it.
7. No usage-based invoicing. Allowances **soft-throttle**; expansion is sold as fixed per-unit
   add-ons. (This also means we never need Stripe metered billing — see §9.)
8. **Publish no price until 30 days of real telemetry exists** (§9).

**Henry decides (only he holds these inputs):**
1. **The actual dollar numbers.** $249 / $899 are grounded recommendations against named anchors, not
   findings. Moving Pro to $199 or $299 changes the margin table, not the structure.
2. **His cost tolerance for the free tier** — is $2.50–$6 per free workspace per month an acceptable
   customer-acquisition cost, or should the dormancy throttle be harsher (7 days? no free SAST?).
3. **Whether the free tier is a growth engine at all.** That is the A-vs-B bet: a slow compounding
   bottom-up funnel vs. a faster, narrower trial funnel with no free surface for Aikido to eat.
4. **Whether to gate `feature.code_security` free.** The single highest-variance decision in this
   document: highest expected conversion lift, highest reputational downside if fix quality is poor.
5. **Whether Premium ships now or waits.** My recommendation is wait — but if he wants three tiers on
   the page for anchoring reasons, that's a positioning judgment, not a technical one.
6. **Whether to publish publicly or price-by-DM for the first ten customers.**

**What nobody can decide yet — and the experiment that would tell us.** We cannot know whether Tom
pays $249 until Tom uses it on his real org. The named experiments, in order:
- **E1 (blocking, 30 days):** read `AiActionDailyRollup` + `DeepRunLog.cost_usd` for observed
  tokens-per-action on real repos, and pull node $/scan-minute from `auto-sec-infra`. **No price is
  published before E1 completes.**
- **E2 (conversion):** instrument one KPI — **median time from signup to first merged draft PR on the
  user's own repo.** If it exceeds 14 days, no pricing works, because the wedge isn't landing.
- **E3 (willingness to pay):** offer Tom Pro at $249 with a founding-customer rate. One real "yes"
  from an operator outweighs every citation in §5.

---

## 9. Implementation note

**Where this lands.** `TIER_FEATURE_MAP` in
`components/shared_platform/application/config/tier_features.py` takes the §2.1 frozensets — this is
ADR 0020's P3 in full. Two mechanics matter:

1. **The plan-tier layer can only turn a flag ON**, and it sits *above* the global layer
   (`user rule → workspace rule → PLAN TIER → global → default`). Since the four scanner flags are in
   `PROD_DISABLED_FLAGS`, mapping them into `_FREE_FEATURES` is what actually lights them up in prod
   for a Free workspace. This works — but it means **a workspace with no Plan row gets nothing**
   (`features_for_tier` returns an empty set for `None`/unknown). Verify every workspace resolves to
   a plan; `Free` is `is_default=True` in `plan_catalog._TIER_BILLING`, and the seeder enforces
   exactly one default, but a workspace created before/outside that path is a silent dark surface.
2. **A user- or workspace-scoped `FeatureFlagRule` overrides the plan tier** by design. That is
   already tracked as the open live-billing hole (task #125): once these flags are revenue-bearing,
   a stray per-user enable is a free upgrade. The fix is not to reorder the resolver (staff overrides
   are legitimate) but to audit-log and periodically reconcile paid-flag rules against plans.

**Flag keys to mint (§2.3):** `feature.scheduled_reports`, `feature.remediation_memory`,
`feature.finding_history` now; `feature.compliance_evidence` and `feature.sso_saml` when their
capabilities exist. Add each to `DEFAULT_FLAGS` in `seed_feature_flags.py` (default off) and to
`PROD_DISABLED_FLAGS` so the plan tier is the only thing that turns them on.

**The quota layer — this is the actual work, and it does not exist.** `TIER_FEATURE_MAP` is a
`dict[str, frozenset[str]]`; it cannot express "3 repos". `EntitlementKey` /
`TIER_CATALOG` / `EntitlementsResolver` in `components/subscription/domain/entitlements.py` is the
right rail and already resolves `plan limits ← workspace overrides` with `None`/`0` = unlimited. What
must be added:

- **New `EntitlementKey` members** (data, not schema — the file says so explicitly):
  `MAX_CLOUD_ACCOUNTS`, `MAX_REPOS`, `MAX_CONTAINER_IMAGES`, `MAX_AI_ACTIONS_PER_MONTH`,
  `MAX_LOG_GB_PER_MONTH`, `SCAN_INTERVAL_HOURS`, `FINDING_RETENTION_DAYS`.
  Keep the existing `MAX_AI_RUNS_PER_MONTH` for *ad-hoc* deep runs — an ad-hoc chat run and a billable
  advisor outcome are different units and conflating them is how the meter drifts.
- **Close `"Premium": {}`.** It currently resolves to unlimited on every dimension including AI runs.
- **Enforcement points.** Counts are cheap: guards at the AWS-connect, repo-allowlist, and
  image-registration use cases (the resolver already exists — this is a day of work per dimension).

**Metering that does NOT exist, and what it costs.** Honest inventory:

| Needed for | Exists today | Gap | Rough build |
|---|---|---|---|
| Cost observability | `DeepRunLog.prompt_tokens/completion_tokens/cost_usd`, `AiActionDailyRollup`, `ExecutionBudget.max_cost_usd` | none — **E1 is a read, not a build** | 0 |
| Count quotas (accounts/repos/images) | `EntitlementsResolver` | guards at 3 use cases + keys | **S** (~2–3 days) |
| **Billable AI-action counter + soft throttle** | nothing | needs a billable-action event emitted at the single choke point (`_finding_processing.process_pending_finding`, the report narrative adapter, the ad-hoc run path), a monthly per-workspace aggregate, and a throttle branch that degrades to critical-only | **M** (~1 week) |
| Log-GB metering | nothing (object counts only, `max_objects=20`/window) | byte accounting in `iter_window_records` + monthly rollup | **M** (~3–5 days) |
| Per-workspace monthly cost ceiling | `ExecutionBudget.max_cost_usd` is **per-run and defaults to `None`** | roll it up to workspace-month; note the meter under-reports where the model catalog is incomplete | **S–M** |
| **Usage-based invoicing (Stripe metered prices)** | not built | **not required by this recommendation** — allowances throttle, expansion is fixed per-unit add-ons which Stripe already handles as plan quantity | **0** (deliberately avoided; would be **L** if we ever meter revenue) |

That last row is the point of the design: **choosing soft-throttle-plus-add-ons over an overage meter
saves the single largest piece of billing engineering, and it is also the choice the market evidence
independently recommends.**

---

## 10. Sources

**Fetched from vendor pricing pages, 2026-08-08:** [aikido.dev/pricing](https://www.aikido.dev/pricing) ·
[prowler.com/pricing](https://prowler.com/pricing) · [wiz.io/pricing](https://www.wiz.io/pricing) ·
[dropzone.ai/pricing](https://www.dropzone.ai/pricing) · [pixee.ai/pricing](https://www.pixee.ai/pricing)

**Vendor / primary documentation:** [Microsoft Security Copilot SCU capacity](https://learn.microsoft.com/en-us/copilot/security/security-compute-units-capacity) ·
[GitHub — Introducing Secret Protection and Code Security (2025-03-04)](https://github.blog/changelog/2025-03-04-introducing-github-secret-protection-and-github-code-security/) ·
[Palo Alto — Prisma Cloud credit licensing guide](https://www.paloaltonetworks.com/resources/guides/prisma-cloud-enterprise-edition-licensing-guide) ·
[Aqua — Trivy unified scanner](https://www.aquasec.com/news/trivy-unified-cloud-native-security-scanner/) ·
[AWS Marketplace — Prowler](https://aws.amazon.com/marketplace/pp/prodview-6ochhig5kxpok) ·
[AWS Marketplace — FortiCNAPP](https://aws.amazon.com/marketplace/pp/prodview-bnqdxtusyye5q) ·
[Cloudflare — Unmetered DDoS Mitigation](https://blog.cloudflare.com/unmetered-mitigation/) ·
[cloudflare.com/plans](https://www.cloudflare.com/plans/)

**Pricing theory & benchmarks:** [Growth Unhinged — State of B2B Monetization 2026 (2026-05-13, n=230)](https://www.growthunhinged.com/p/the-state-of-b2b-monetization-in-2026) ·
[Revenue Creator / Kyle Poyar — why hybrid pricing won (2026-05-27)](https://www.revenuecreator.com/p/why-hybrid-pricing-already-won-the-ai-era-kyle-poyar-growth-unhinged) ·
[ICONIQ Growth — State of AI (2026-07)](https://cdn.prod.website-files.com/65d0d38fc4ec8ce8a8921654/6a46e77c8e76fa41d3eba385_ICONIQ%20Analytics%20-%20State%20of%20AI%20July%202026.pdf) ·
[SaaS Mag — The AI COGS problem (2026)](https://www.saasmag.com/ai-cogs-saas-gross-margin-compression/) ·
[Software Pricing Partners — AI Metering Field Guide (2026-06-02)](https://softwarepricing.com/blog/usage-based-pricing-backfire-field-guide/) ·
[— Credit-Based Pricing: Six Fatal Flaws (2026-04-16)](https://softwarepricing.com/blog/credit-based-pricing-ai/) ·
[Artisan Growth Strategies — freemium conversion benchmarks (2026)](https://www.artisangrowthstrategies.com/blog/freemium-conversion-rate-benchmarks) ·
[acceleroi — PLG free-to-paid benchmarks](https://www.acceleroi.com/blog/benchmarks/saas-plg-free-to-paid-conversion-rate) ·
[CloudZero — value metrics](https://www.cloudzero.com/blog/value-metrics/) ·
[Joel Spolsky — Strategy Letter V (2002-06-12)](https://www.joelonsoftware.com/2002/06/12/strategy-letter-v/)

**AI-SOC / metering commentary:** [Prophet Security — AI SOC pricing models compared (2026-06-18)](https://www.prophetsecurity.ai/blog/ai-soc-pricing-models) ·
[UnderDefense — AI SOC pricing (2026-07-13)](https://underdefense.com/blog/ai-soc-pricing/) ·
[UnderDefense — Dropzone pricing (2026)](https://underdefense.com/blog/dropzone-pricing/) ·
[Security Boulevard — The AI meter vs the AI in the price (2026-08)](https://securityboulevard.com/2026/08/the-ai-meter-vs-the-ai-in-the-price-why-predictable-wins-at-renewal/) ·
[Root Evidence — cyber security incentives](https://www.rootevidence.com/blog-posts/cyber-security-incentives) ·
[Packetlabs — pentest retest incentives](https://www.packetlabs.net/posts/penetration-testing-vendor-fix-findings) ·
[SAMexpert — Security Copilot licensing guide](https://samexpert.com/security-copilot-licensing-guide/)

**Third-party price estimates (aggregators — treat as low-confidence, not vendor-published):**
[wizpricing.com](https://www.wizpricing.com/pricing-model) · [comparedge — Wiz](https://comparedge.com/tools/wiz/pricing) ·
[Modern DataTools — Orca](https://www.modern-datatools.com/tools/orca-security/pricing) · [Vendr — Orca](https://www.vendr.com/marketplace/orca-security) ·
[cubeapm — Sysdig](https://cubeapm.com/blog/sysdig-pricing-review/) · [Modern DataTools — Prisma](https://www.modern-datatools.com/tools/prisma-cloud/pricing) ·
[PeerSpot — FortiCNAPP](https://www.peerspot.com/products/lacework-forticnapp-reviews) · [Modern DataTools — Aqua](https://www.modern-datatools.com/tools/aqua-security/pricing) ·
[dev.to — Semgrep pricing 2026](https://dev.to/rahulxsingh/semgrep-pricing-in-2026-open-source-vs-team-vs-enterprise-costs-3dic) ·
[dev.to — Snyk pricing 2026](https://dev.to/rahulxsingh/snyk-pricing-in-2026-free-plan-team-business-and-enterprise-costs-breakdown-5e88) ·
[dev.to — CodeRabbit pricing 2026](https://dev.to/rahulxsingh/coderabbit-pricing-in-2026-free-tier-pro-plans-and-enterprise-costs-1pc4) ·
[soc2auditors — SOC 2 software pricing comparison (2026-08-03)](https://soc2auditors.org/insights/soc-2-software-pricing-comparison/) ·
[soc2auditors — Vanta pricing](https://soc2auditors.org/insights/vanta-pricing/) ·
[reo.dev — Snyk GTM](https://www.reo.dev/blog/from-open-source-to-343m-arr-how-snyk-made-developers-its-secret-weapon) ·
[Unusual VC — Snyk PMF](https://www.unusual.vc/how-snyk-found-product-market-fit-guy-podjarny-on-building-a-dev-centric-security-company/) ·
[EntrepreneurLoop — Gemini free-tier quota cuts (2025-12-07)](https://entrepreneurloop.com/ai-free-tier-limits-tighten-as-openai-and-google-face-rising-infrastructure-costs/) ·
[BVP — Upwind](https://www.bvp.com/news/securing-the-next-generation-of-cloud-and-ai-workloads-with-upwind) ·
[saas-expert — Prowler review](https://saas-expert.com/articles/prowler-review/)

**In-repo (verified 2026-08-08):** `components/shared_platform/application/config/tier_features.py:32-41` ·
`components/subscription/domain/entitlements.py:34-57,149-165` ·
`components/subscription/application/config/plan_catalog.py:24-28` ·
`components/shared_platform/cli/management/commands/seed_feature_flags.py:27-136` ·
`components/cloud_graph/domain/services/attack_path_remediation_advisor.py:7` ·
`components/container_security/domain/services/container_vuln_remediation_advisor.py:5` ·
`components/agents/infrastructure/adapters/langchain/tools/finding_verifier.py:14` ·
`components/agents/infrastructure/adapters/langchain/tools/_finding_processing.py:159-183` ·
`components/agents/infrastructure/adapters/langchain/deep/costing.py:31-53` ·
`components/agents/cli/management/commands/seed_ai_models.py:55-57` ·
`components/scanning/infrastructure/backends/k8s_job_backend.py:99-140` ·
open tasks #93 (provenance drill), #117 (SAST fix quality), #125 (user-flag bypasses plan tier).
