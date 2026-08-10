# ADR 0023 — Agent runtime accountability: turning our own agent-governance substrate outward, so a customer can prove what their AI agents did, with what tool access, under what identity

Status: **Proposed (2026-08-09) — design only; build deferred** until Henry's explicit go per phase,
and sequenced behind the standing "harden the core loops for Tom's real use + go-live" priority.

Relates to: **ADR 0004** (Finding SSOT + asset-graph hub-and-spoke — this ADR adds a source and a URN
namespace to that spine, never a parallel store), **ADR 0006** (scanner-execution substrate),
**ADR 0008** (`LogSourcePort` — the registry template, third use, and the fallback capture path),
**ADR 0009** (compliance lens / audit-grade evidence with provenance — the downstream consumer),
**ADR 0010** (multi-provider `VcsPort` — the token-shaped connection + `repo_allowlist` consent
template), **ADR 0012** (Remediation Memory), **ADR 0013** (contextual risk), **ADR 0016** (delivery
channel port), **ADR 0021** (Vercel posture provider — the closest precedent: the same named buyer,
the same estate, the `VercelConnection` row this ADR reuses, and the D5 refusal of Vercel log
ingestion that constrains the capture decision here).

Extends, and does not duplicate: `docs/plans/AI_SECURITY_ARTICLE_MAPPING_2026-08-08.md` (see §1.3),
`docs/competitive/LANDSCAPE_2026-08.md` §5, `docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md` §3.4,
`docs/architecture/ARCHITECTURE_REVIEW_2026-08-09.md` §1.1.

Working research notes (citations, rejected options, what could not be verified):
`docs/plans/AGENT_RUNTIME_ACCOUNTABILITY_RESEARCH_2026-08-09.md`.

---

## 1. Context

### 1.1 Henry's question, in his words

> *"What are a customer's AI agents actually doing, with what tool access, under what identity,
> logged and provable after the fact."*

Four clauses, and they are four different engineering problems: **behaviour** (what did it do),
**capability** (what could it have done), **identity** (as whom), and **provability** (can you show a
third party afterwards). A design that answers only the first is a trace viewer, and trace viewers
are a solved, commoditized, acquired market (§5). The product is in the join.

### 1.2 The named buyer this is designed for

**Isaac** — the first real buyer signal in the outreach tracker, and the same buyer ADR 0021 is
designed around:

- **~60 AI agents in production**, doing client-facing work.
- **Handles card data via Stripe.**
- **No security team.** Ships fast.
- **On Vercel** (confirmed 2026-08-09, ADR 0021 §"customer-driven work").

Every design choice below is scored against *his* estate, not a hypothetical enterprise with a
platform team who will happily instrument 60 services. Concretely that means: **any capture
mechanism whose deployment cost scales with the number of agents is disqualified**, because 60 × any
per-agent integration is a quarter of engineering time Isaac does not have and will not spend on a
tool he has not yet bought.

### 1.3 How this relates to the research we already did

`docs/plans/AI_SECURITY_ARTICLE_MAPPING_2026-08-08.md` scoped two adjacent capabilities. This ADR is
**neither**, and the distinction is load-bearing enough to state as a table:

| Prior item | What it is | Relationship |
|---|---|---|
| **Lens-B #1** — AI-SPM red-teaming pillar (Garak behind `ScannerPort`) | **Attacks** the customer's AI endpoints with synthetic probes for injection / jailbreak / leakage | **Sibling.** Different verb (probe vs observe), different data (synthetic attacks vs real production actions), different finding class ("this endpoint is jailbreakable" vs "this agent used a Stripe write scope on Tuesday"). They share the SSOT landing zone and nothing else. Neither blocks the other. |
| **Lens-B #2** — shadow-AI discovery over customer logs | **Discovers** unsanctioned AI usage (LLM-provider egress in CloudTrail / app logs) | **Prerequisite fragment, and a cautionary tale.** Discovery answers *"an agent exists"* — which is an **absence**-anchored statement and therefore the exact trap Henry's moat rule forbids. This ADR is what converts that signal into an exposure statement. Its log-derived mechanism is this ADR's fallback capture path (§3). |
| **Lens-B #3** — customer AI governance pack (comply lens) | Inventory + risk register + NIST/ATLAS control mapping | **Downstream consumer.** It needs the inventory and the evidence this ADR produces. It cannot be built first, and building it first would produce a register with nothing verifiable in it. |
| **Lens-A adopt #2** — security detections over OUR OWN AI telemetry | Detectors over `DeepRunLog` feeding the Finding SSOT | **The dogfood of this ADR's detection layer** — same detection vocabulary, pointed inward first, on data we already hold. |

**Verdict: this ADR supersedes nothing. It is the sibling of Lens-B #1, the completion of Lens-B #2,
and the prerequisite of Lens-B #3.**

`docs/architecture/ARCHITECTURE_REVIEW_2026-08-09.md` §1.1 independently reached the same place and
pre-authorized this document:

> "Provenance/audit of **our own agents** is BUILT and is a strength … Monitoring the **customer's**
> agents (Isaac's ~60: 'what did MY agents do, under what identity') is the genuinely unbuilt bet.
> **There is no ADR for it** … When you decide to build it, that's the moment it gets an ADR."

### 1.4 The hard design rule: exposure-anchored, never absence-anchored

Henry's standing constraint, derived from three prior ideas that died on precisely this
(`STATE_AND_VISION.md` §1.1 standing note):

> **"This agent holds write access to Stripe and used it on Tuesday under this identity — here is
> the trace"** is the product.
> **"You lack visibility into your agents"** is the trap.

`STATE_AND_VISION.md` §1.1 states the engineering consequence: *"write exposure-anchored rules,
never absence-anchored ones"* — match the risky property **joined to** reachability in the graph.
That converts a precision problem (hard) into a filter problem (tractable), and the filter is the
moat.

Applied here, this rule is not a slogan — it is a **test every capability in §4 must pass**, and
each one below carries its terminal exposure statement explicitly. A capability that can only
produce "we don't know" output does not ship.

---

## 2. Research grounding

_(claim → source; full notes and rejected options in
`docs/plans/AGENT_RUNTIME_ACCOUNTABILITY_RESEARCH_2026-08-09.md`)_

**TO BE COMPLETED — research streams in flight.**

---

## 3. Decisions

**TO BE COMPLETED.**

---

## 4. What lands as findings

**TO BE COMPLETED.**

---

## 5. Feature or company?

**TO BE COMPLETED.**

---

## 6. Phasing

**TO BE COMPLETED.**

---

## 7. Open questions

**TO BE COMPLETED.**
