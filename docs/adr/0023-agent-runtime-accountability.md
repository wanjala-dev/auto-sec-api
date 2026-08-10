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

## 2. The running start, measured honestly

The thesis under test: *turning our own accountability substrate outward is a much shorter path than
building AI-SPM from scratch.* We mapped every named component in code (full field lists and file
paths in the research notes §3). **The verdict is a split, and the split is the most important
engineering fact in this ADR.**

### 2.1 The half that ports outward (essentially free)

| Component | What it captures | Why it ports |
|---|---|---|
| **`provenance` graph** — `ProvenanceActor` / `ProvenanceResource` / `AccessGrant` / `ProvenanceEvent` (`infrastructure/persistence/provenance/models.py`) | **`AccessGrant` = the potential (CAN). `ProvenanceEvent` = the actual (DID).** Actor carries `actor_type`, `source_system`, `external_ref`, optional `user` FK, `agent_ref`. Resource carries `asset_urn`, stamped by a signal bridge. | **`ActorType` already includes `ai_agent` and `vendor_integration`; `SourceSystem` already enumerates `aws / okta / google_workspace / slack / github`; `ProvenanceEvent.Origin` already includes `vendor_log`.** It is explicitly a *projection index over source-of-truth stores*, idempotent on `(workspace, origin, origin_id)`. Three backfills already exist for internal origins; a fourth for external agents is the same pattern. |
| **`EntityAuditLog`** (`infrastructure/persistence/audit/models.py`) | Generic-FK field-level change trail with `actor`, `reason`, before/after JSON | Zero schema change for a new entity type. Read authz is deliberately **membership, not admin** — the read-only auditor persona already works. |
| **`sign_off` kernel** (`components/sign_off/`) | `PENDING → APPROVED / CHANGES_REQUESTED / REJECTED`; risk bands govern friction never bypass; **anti-rubber-stamp `ReviewerReceipts`**; `approve()` raises unless a RED decision carries an `override_reason`; `require_approved()` is the enforcement teeth | **Pure ABC + value-object kernel with zero runtime assumptions — the single most portable asset in the repo.** |
| **`response` action ledger** (`components/response/`) | `PROPOSED → EXECUTED → ROLLED_BACK`; `spec`/`inverse_spec` written once and never changed; dry-run defaults true at three layers | `requested_by` is a bare `CharField(64)` — an external agent id fits with no migration. |
| **Board provenance** (`project.Task.metadata["provenance"]`) | Append-only event list; the draft-PR writer stamps **`"actor": "agent:<agent> via user:<human>"`** | That dual-principal string is already the delegated-identity shape §3.3 needs. |
| **WS redaction + owner-only run detail** | Six-key payload allowlist, 100-char scalar cap, tool IO/prompts owner-only, tested against the serialized envelope | Operates on **stored rows**, so it works unchanged over externally-reported data. A tested least-disclosure read contract for agent traces is not a small thing to already own. |
| **Finding SSOT + board/triage/draft-PR loop** | `Finding.source` is a **free CharField** and `attributes` is a JSON bag | **A new finding kind needs no migration.** |

### 2.2 The half that does NOT port (this is the real work)

| Component | Why it is irreducibly ours |
|---|---|
| **`DeepRunLog` writer** | `log_deep_event(thread_id, …)` resolves the run by an **in-process `thread_id`** and reads LangChain's `intermediate_steps` directly. The REST surface is **read-only — there is no ingest endpoint.** The *schema* is source-agnostic; the *writer* is not. |
| **Tool-risk gate** (`tool_risk.py` + `@tool(risk=…)`) | A **Python decorator wrapping a bound method on our `BaseAgent`. It cannot observe a tool call it does not wrap.** The tier taxonomy and refusal semantics port; the enforcement mechanism cannot. |
| **Langfuse / `TracingPort`** | **Outbound-only: the port has no read or query verb at all.** Our queryable evidence store is Postgres, not Langfuse. |
| **AI service principal** (SEE-201) | The *concept* (agent as first-class principal, own grant, asymmetric read-all/write-nothing cap) ports perfectly. The *implementation* mints a real Django `CustomUser` with a synthetic email so `Task.created_by` satisfies membership checks — which does not fit an external agent identity. |

### 2.3 Verdict

**Confirmed for the back half; refuted for the front half.** We already own storage, correlation,
identity modelling, approval, evidence and remediation — that is most of a product, and it is why
this is a credible bet rather than a from-scratch AI-SPM build. But **capture is genuinely net-new,
and capture is the entire risk.** Any phase plan that treats capture as the easy first step is wrong.

### 2.4 Five gaps to state plainly (they bound what we may promise)

1. **"Provably logged" is today only "conventionally logged."** `DeepRunLog` and `EntityAuditLog` are
   append-only by convention and documentation — **no DB constraint, no hash chain, no signature, no
   retention policy** — and both CASCADE-delete with their parent.
2. **No FK from an AI action to the run that produced it** — the link is
   `Task.metadata["run_telemetry"]["source_thread_id"]`, stamped by a **heuristic** time+agent match.
3. **Tool-risk refusals have no first-class event type** — a denial is a return string that survives
   only inside a `tool_observation` payload. We cannot honestly sell "provable denials" today.
4. **The `sign_off` registry ships with zero registered adapters** — the kernel is real and unwired.
5. **`TracingPort` has no query verb** — Langfuse cannot back a customer-facing feature as-is.

Items 1 and 3 are prerequisites for the word "provable" in the product claim, and they are
**inward** work we should do anyway (they improve our own posture). That is a happy alignment, and
§6 sequences them accordingly.

### 2.5 Correction to a premise

`AIAction` **no longer exists** — it was deleted in Phase 5 of the Agents-as-Teammates migration. An
"AI action" today is a `project.Task` row with `source_type="ai.<action_type>"` written by
`persist_finding_as_task`. Any design or prose that references the `AIAction` table is stale.

---

## 3. Decisions

### D1 — The data model is the **existing `provenance` context**, extended with an external origin. No new bounded context, no per-pillar tables. **[proposed]**

`ProvenanceActor` / `ProvenanceResource` / `AccessGrant` / `ProvenanceEvent` already express every
noun in Henry's question, and ADR 0004's hub-and-spoke rule forbids a parallel store. The mapping:

| Henry's noun | Our SSOT term |
|---|---|
| an **agent** | `ProvenanceActor(actor_type=ai_agent, source_system=<customer platform>, external_ref=<their agent id>)` |
| an **identity** | the same actor row; `user` FK when the agent acts as a known human, `external_ref` otherwise |
| a **tool grant** (CAN) | `AccessGrant(actor → resource, permissions[], scope, granted_at, revoked_at)` |
| an **agent action** (DID) | `ProvenanceEvent(actor, resource, action, occurred_at, metadata{tool, request_id, …}, origin, origin_id)` |
| the **thing it touched** | `ProvenanceResource.asset_urn` → joins the asset graph **by value**, never FK |
| the **exposure statement** | a `Finding` with a new `source` slug (free CharField — no migration) |

Three concrete extensions, all additive:

1. **A new `ProvenanceEvent.Origin` value** for externally-captured agent activity (the enum already
   carries `vendor_log`; whether we reuse it or add `agent_runtime` is an implementation detail
   settled at build time — the idempotency key `(workspace, origin, origin_id)` is what matters).
2. **A decided URN namespace** — `urn:agent:<platform>:<external_ref>` — registered in the ADR, never
   defaulted. ADR 0021 D1's trap applies verbatim: a wrongly-namespaced URN "would not fail loudly;
   it would succeed and lie."
3. **A capture-connection model** for the customer's agent platform, copying `WorkspaceLogSource`'s
   `kind + config(JSON) + secret_ref + cursor + status` shape and `VercelConnection`'s named-scope
   consent shape. This is the registry template's **sixth** use (ADR 0008 → 0010 → 0016 → 0019 →
   0021 → here); it is not a new pattern.

**Explicitly rejected:** a new `ai_estate` bounded context, an `AgentRun` table mirroring
`DeepRunLog` for customer data, and any per-platform findings table. `Finding.source` +
`attributes` + the provenance graph carry all of it.

**One honest caveat:** `feature.provenance_graph` is **dark today**. This ADR therefore depends on
un-darkening it (which ADR 0009 D5 already wants for access-review evidence) — a shared prerequisite,
not a hidden cost. It should be named in the phase plan, not discovered during it.

### D2 — Capture: **primary = Vercel Trace Drain + AI SDK `registerTelemetry()`; fallback = Trace Drain alone (zero code change).** Identity is a **join we perform**, never a field we read. **[proposed]**

**The finding that determines this decision**, verified across the OTel registry, the GenAI
agent-spans document, and the genai repo's own attribute registry:

> **There is no principal, subject, credential, or authorization attribute anywhere in the `gen_ai.*`
> namespace.** The only protocol-verified identity in any capture mechanism is MCP's OAuth token
> `sub`, and MCP Authorization is optional and covers only MCP-routed tools.
> **Every accountability claim a security product makes here is a JOIN it performs, not a field it
> reads.** That join — behaviour telemetry × credential provenance — **is the defensible product
> surface.**

So capture must be designed as **two independent axes that we correlate**, not one feed:

| Axis | What it gives | How we get it for Isaac |
|---|---|---|
| **Behaviour** | which agent, which tool, which resource, when, with what outcome | Vercel Trace Drain (platform fetch spans) + AI SDK `execute_tool` spans |
| **Capability / identity** | what the agent COULD do, and as whom | MCP `tools/list`, Stripe restricted-key permissions, IdP scope APIs, cloud IAM — **read from the grant surface, not the telemetry** |

#### Primary: AI SDK `registerTelemetry()` → Vercel Trace Drain → our OTLP endpoint

- **AI SDK 7** ships `registerTelemetry(new OpenTelemetry())` — **one line, once, at startup**, after
  which *"all AI SDK calls emit telemetry events by default"*. It emits native GenAI-semconv spans
  including **`execute_tool {toolName}`** with `gen_ai.tool.name`, `.call.id`, and (opt-out)
  arguments and results. **This is the only mechanism that sees the tool layer.**
- **Vercel Trace Drains** carry those spans out over **OTLP/HTTP** to any custom endpoint, and are
  **provisionable by us through the Drains REST API** rather than a UI walkthrough. They also carry
  Vercel's own **outbound fetch spans**, so the LLM hop *and* the direct-to-Stripe hop arrive **in one
  correlated trace under the same `traceId`**.
- **Why this composition and not a gateway:** a gateway sits on the path to the *model provider*. The
  agent's `charge_card` tool calling `api.stripe.com` **traverses no gateway**. *Any architecture
  relying on gateway logs alone is blind precisely where money moves.* A gateway also cannot prove
  its own coverage — an agent with a stray raw provider key is invisible to it.

**Three conditions stated plainly, because they can invalidate the plan:**

1. ⚠ **Confirm Isaac is on AI SDK 7.** On **v6 and earlier** the API is per-call
   `experimental_telemetry: { isEnabled: true }` — **the friction inverts from one edit to sixty.**
   This is the single highest-leverage question to ask him (§7).
2. ⚠ **Default `recordInputs: false` / `recordOutputs: false`.** The AI SDK records inputs and outputs
   **by default** — the *opposite* of the OTel spec's Opt-In posture. For a customer handling card
   data, shipping prompts and tool arguments to our sink by accident is unacceptable. **Metadata-only
   is the default; content capture is separately consented** (D3).
3. ⚠ **Trace Drains are Pro/Enterprise at $0.50/GB on the customer's bill.** Mitigate with the
   per-drain sampling rules (by environment, percentage, path prefix).

#### Fallback: Trace Drain alone — genuinely zero code change

Verified verbatim (https://vercel.com/docs/tracing): *"Vercel automatically instruments your
application **without needing any additional code changes** … **Outbound HTTP calls**: The HTTP
requests made from your function will be displayed as **fetch spans**."*

This answers *"which of these deployments talk to `api.stripe.com`, and which talk to LLM
providers"* — inventory and egress — **without touching a line of Isaac's code**, with the drain
provisioned by API. What it does **not** give: tool semantics, content, or any notion of which agent
or credential acted. Those need the primary path or the identity axis layered on.

#### How this squares with ADR 0021 D5 (stated explicitly — this is not a silent re-opening)

ADR 0021 D5 refused Vercel **Log** Drains. **Trace** Drains are a different product with a different
data shape:

| D5's reason | Binds Trace Drains? |
|---|---|
| No `logs` integration scope (runtime logs 403 with every scope) | **No** — Trace Drains use the Drains REST API, a different surface. |
| **Pro/Enterprise, $0.50/GB on the customer's bill** | **YES — inherited identically.** Mitigated by per-drain sampling. |
| Drain payloads are **attacker-authored strings** entering the AI pipeline | **Materially weaker** — fetch spans are platform-generated (host, method, status, duration), not attacker-authored free text. ⚠ **But this protection evaporates the moment content attributes are enabled**, because `gen_ai.input.messages` *is* attacker-influenced text. **This is the second reason content capture is off by default** (D3), and if it is ever enabled, D5's injection-fence condition applies in full. |

#### Explicitly rejected as the primary mechanism

- **LLM gateway / egress proxy** (incl. Vercel AI Gateway) — **blind to tool execution and to
  direct-to-Stripe calls**, and cannot prove its own coverage. **Retained for one purpose only:** its
  `ai-reporting-user` / `ai-reporting-tags` headers are documented for stamping context *"without
  modifying application code"* and become queryable dimensions — **the cheapest per-agent identity
  axis that exists**, and therefore a genuinely useful *supplement*.
- **Log-based reconstruction from Vercel runtime logs** — Log Drains carry **no outbound-call field
  at all**, and retention is **1 hour on Hobby, 1 day on Pro, 3 days on Enterprise** (30 days only
  with paid Observability Plus). ⚠ **This forces an honest product framing: we turn on accountability
  going forward. We are not a forensic-recovery tool, and we must never imply we are.**
- **MCP server-side capture as the primary** — the spec provides **no audit event schema, no
  tool-call recording standard, no correlation ID, no retention or tamper-evidence model** (the two
  SEPs that would fix this, SEP-2817 and SEP-3004, are **unmerged and unsponsored**), MCP `logging`
  is server→client and now **deprecated**, and it covers only MCP-routed tools. **Retained for one
  high-value purpose:** `tools/list` + `notifications/tools/list_changed` is the **best capability
  enumeration surface that exists** and gives real-time capability-drift detection (finding F4) —
  and MCP's OAuth `sub` is the only protocol-verified identity available anywhere.
- **OTel GenAI semconv as a dependency to pin** — it is a *schema*, not a mechanism, and ⚠ **the
  split-out `semantic-conventions-genai` repo has NO releases or tags**, so pinning means pinning a
  commit on `main`. Under `pin-versions.md` that is a real exposure; we consume the shape
  defensively and normalize, rather than treating it as a stable contract. Budget for a
  **normalization layer**, since OpenInference (Arize) is a *competing* convention we will also see.

#### The identity axis, concretely (the join's other half)

Identity does not come from telemetry. It comes from the **grant surface**, and the highest-leverage
recommendation we can make to Isaac is a **provisioning** change, not a logging one:

> **Stripe's own documentation says it for us:** *"Stripe recommends always using restricted API keys
> instead of unrestricted secret keys, **especially when giving a key to an AI agent**"* and *"**use
> one restricted key per service or use case.**"* Stripe request logs are **per-key** — so per-agent
> Stripe attribution works **if and only if keys are per-agent.**

**And the honest limit, which must appear in the product copy, not just the ADR:** where a customer
runs 60 agents on one shared key, *"there is no reliable way to tell who used the key"* (Google Cloud
IAM). **For shared-key estates we are reconstructing, not proving** — and F3 exists precisely to make
that reconstruction gap itself the exposure statement.

### D6 — Tamper-evidence: Tier 1 now, Tier 2 when the first auditor asks, and **ship a verifier the customer can run against us** — or the claim is theatre. **[proposed]**

Our current honest position (§2.4): `DeepRunLog` and `EntityAuditLog` are append-only **by convention
and documentation only** — no DB constraint, no hash chain, no signature, no retention policy.
"Provable after the fact" is therefore **not a claim we may make today.**

**Tier 1 — non-negotiable before the word "provable" is used in any customer-facing surface:**
1. **Append-only by construction** — INSERT-only grant for the emitter; corrections are new
   compensating records, never edits.
2. **Per-record hash chain** — `prev_hash` + `hash = SHA-256(canonical_serialization || prev_hash)`.
3. ⚠ **Canonical serialization, pinned and versioned.** Serialization drift silently makes every
   historical hash unverifiable — *the most common way homegrown chains die.*
4. **Evidence in a different trust domain from the system that writes it.** This is what SOC 2
   auditors actually look for, and it does more real work than any cryptography.
5. ⭐ **A standalone verifier the customer can run themselves.** **Without this, everything above is
   theatre.** The test: *does the customer possess a tool that can independently detect tampering —
   including tampering by us?* AWS passes (`aws cloudtrail validate-logs`); most "immutable audit
   log" SaaS does not.
6. **Retention: 12 months, 3 months hot.**

**Tier 2 — when the first buyer with a QSA asks:** a periodic **Merkle root per window**, stored
**in a separate location from the records** (CloudTrail's separated-digest-folder pattern, which also
"permits existing log processing solutions to continue to operate without modification"); roots
**signed** with KMS-held keys; roots **published where the customer can see them but we cannot
silently rewrite them** (a customer-owned bucket, or emailed to their security contact) — the
cheapest possible witness, and what makes a full-chain rewrite *by us* detectable; and **stapled
inclusion proofs on exported artifacts**, so a single finding can be verified without trusting us and
without downloading the log.

**Explicitly not built:** a bespoke ledger database (⚠ **Amazon QLDB was retired 2025-07-31 and AWS
now recommends Aurora PostgreSQL, which explicitly does not provide cryptographic verifiability** —
if a hyperscaler could not sustain a managed cryptographic-ledger business, we must not make one
load-bearing), blockchain anchoring, or per-record third-party timestamping. S3 Object Lock only on
contractual demand, and **Governance mode never Compliance** — an accidental multi-year retention in
Compliance mode is genuinely unfixable.

**The compliance hook that makes this concrete rather than aspirational:** PCI DSS v4.0 requires
**12 months of audit-log retention with 3 months immediately available**; **Stripe's own Activity
Logs retain 6 months.** For a card-handling customer, **Stripe's retention cannot satisfy the
requirement** — an independent evidence store is not a nice-to-have, it is the gap.
⚠ **Verification flag: the PCI requirement numbering (10.3.2 / 10.3.4 / 10.5.1) is corroborated only
across QSA and vendor secondary sources, not fetched from the PCI SSC primary document. Older sources
use the v3.2.1 number 10.5.5 for what is now 10.3.4. Confirm against the PCI SSC library before any
customer-facing use** — a wrong requirement number is exactly what a QSA notices.

**And the honest sentence that bounds the whole capability:**

> Tamper-evidence proves our records **were not altered after we wrote them**. It does not prove they
> **were true when we wrote them.** The truth of the record rests on the fidelity of collection — and
> a shared API key means the record cannot have been true about *which agent acted* in the first
> place. **No amount of cryptography downstream repairs an attribution that was never captured.**

That dependency — **identity first, then permissions, then evidence** — is the spine of the phase
plan in §6.

### D3 — Consent boundary: read-only, named-scope, fail-closed — the `repo_allowlist` / ExternalId pattern, sixth use. **[proposed]**

- **An `agent_allowlist`** on the capture connection, mirroring `VcsConnection.repo_allowlist`
  exactly — an explicit list of the agents/projects/environments we may observe. **Enforced at every
  layer, fail-closed**, the way `repo_allowlist` is enforced at five (trigger-time resolve,
  read-time re-check, listing, per-file read pinned to a resolved ref, and the write path). A
  credential vend that returns `None` **fails the run loudly** rather than proceeding consentlessly.
- **Never auto-discover.** ADR 0021 D3 named Prowler's "no team ⇒ scan every team the token can see"
  behaviour *"a consent violation in our model."* The identical rule binds here: we observe exactly
  the agents named in the allowlist, never every agent a credential can reach. This matters more
  here than anywhere else in the product, because agent telemetry contains **prompts and tool
  arguments** — i.e. potentially the customer's end-users' data.
- **Read-only, always.** The only write path in the entire product is `open_draft_pr` (never merges),
  plus `components/response` behind propose→approve→execute with dry-run default. **This ADR adds no
  new write scope** (see D5 on remediation).
- **Secrets** ride the ONE integrations Fernet envelope (`secret_envelope.py`), never plaintext,
  never logged, `@sensitive_variables` applied; decrypt failure raises loudly.
- **Data minimisation is a first-class requirement, not a nicety.** Prompts and tool arguments are
  the highest-sensitivity data we would ever hold. The default posture is **metadata-only capture**
  (which agent, which tool, which resource, which identity, when, allowed/denied) with
  **content capture off by default and separately consented**. The existing WS-redaction contract
  (§2.1) is the enforcement precedent, and the existing owner-only run-detail rule is the read
  precedent — a customer's agent trace content must never be visible to every workspace member by
  default.
- **Flag-gated dark** behind its own `feature.*` flag — a **sibling**, never a reuse of an adjacent
  flag (ADR 0021 D6: "a workspace opted into AWS CSPM has not consented to a Vercel scan surface").
  Seeded in `seed_feature_flags`, listed in `PROD_DISABLED_FLAGS`, un-darkened per workspace, and
  **fail closed** (missing ⇒ off).

### D4 — Findings: every capability terminates in an exposure statement, or it does not ship. **[proposed]**

This is the operationalisation of Henry's moat rule. Each proposed detector is listed with the
sentence it must be able to produce; **a detector that can only produce an absence statement is
rejected by construction.**

| # | Detector | Terminal exposure statement | Absence-anchored version (**forbidden**) |
|---|---|---|---|
| **F1** | **Granted-but-unused capability** (`AccessGrant` with no corresponding `ProvenanceEvent` in the window) | *"Agent `invoice-bot` holds **write** on Stripe. It has not used it in 30 days. Here are the 0 events."* | ~~"You may have over-permissioned agents."~~ |
| **F2** | **High-risk capability exercised** (a `ProvenanceEvent` against a resource whose grant is `write`/`admin` on a payment/PII system) | *"Agent `refund-agent` used **write** on Stripe on Tuesday 14:03 UTC under identity `sa-refunds`, acting for `isaac@…`. Here is the event and the trace."* | ~~"Your agents access sensitive systems."~~ |
| **F3** | **Ungoverned identity** (an agent whose actions resolve to a **shared human or root credential** rather than a distinct principal) | *"These 12 agents all act as `isaac@…`. An action by any of them is **indistinguishable** from an action by Isaac — attribution is impossible for this set."* | ~~"You lack agent identity."~~ (⚠ this one is closest to the trap; the exposure framing is *attribution is impossible for these specific 12*, evidenced by the events themselves) |
| **F4** | **Capability drift** (a grant appearing that was not present at the last observation) | *"Agent `support-bot` gained **admin** on the customer database on 2026-08-04; it held **read** before."* | ~~"Permissions may have changed."~~ |
| **F5** | **Agent-reachable exposure join** (an agent grant against a resource the asset graph marks `PUBLIC`, or on a finding's `asset_urn`) | *"Agent `deploy-bot` can write to the S3 bucket that this **critical public-exposure finding** is about."* — **the moat sentence, replayed on agents** | ~~"Agents touch cloud resources."~~ |

**F5 is the differentiated one and the reason this belongs in Auto-Sec rather than in a trace
viewer.** Everything else on this list is, in principle, buildable by an observability vendor. F5
requires the asset graph and the Finding SSOT, which is exactly the claim `STATE_AND_VISION.md` §1.1
makes about the whole product: *"'this handler has no authorization check' is a commodity finding …
'**and it is internet-reachable via this IAM path**' can only be said by something holding the cloud
graph."*

**Board/triage wiring** is the proven four-step recipe, sixth use: emit `FindingObserved` with the
new `source` → add a `_SOURCE_BOARD[source]` entry (unmapped sources **silently no-op**) → add the
board `source_type` to `ROUTABLE_SOURCE_TYPES` → **ship the specialist's triage tool in the same
phase** (`triage.py`'s own docstring: *"routable without a tool is a silent no-op"*).

### D5 — Remediation: propose, never execute. The honest answer is that draft-PR does not fit, and we should not pretend otherwise. **[proposed]**

`remediation_target(source_type, payload)` resolves to `TARGET_REPO | TARGET_IMAGE | TARGET_CLOUD |
TARGET_SERVICE | TARGET_NONE`, and **only `TARGET_REPO` gets the draft-PR affordance.** So what does
"fix an over-permissioned agent" mean?

Three cases, ranked by how honest we can be about each:

1. **The grant lives in code the customer owns** (a tool manifest, an `mcp.json`, a tools array in
   the agent's source, an IAM policy in Terraform) → **`TARGET_REPO`, and the existing draft-PR
   engine applies unchanged** — a new *patch strategy* on the ONE engine, never a second engine
   (ADR 0017 D0). This is the best case and the one to aim the proof at.
2. **The grant lives in a console/API** (an OAuth scope, a platform-managed key) → **`TARGET_CLOUD`
   / `TARGET_SERVICE`**: a **proposed** response action. Note the standing constraint from
   `ProposeResponseActionUseCase`: *"Proposing has NO external effect … That is why an autonomous
   agent is allowed to propose (a `reversible_write`) while only a human may approve the execution
   (the `irreversible` step)."* But §2.4 gap and the code map are blunt — the response framework is
   **a two-value enum today** (`REVOKE_SG_INGRESS` / `AUTHORIZE_SG_INGRESS`) and approve-to-execute
   is minimal. **Revoking an agent scope is therefore a real build, not a wiring exercise**, and must
   not be scoped as if the rail already exists.
3. **The grant is architectural** (the agent uses a shared human credential — F3) → **`TARGET_NONE`
   for automation.** The deliverable is the evidence plus a specific recommendation. Pretending to
   automate an identity re-architecture would be the kind of overclaim an operator catches in five
   minutes.

**Standing rule that binds all three** (memory: *finding must carry artifact*): a grounding failure
downgrades the **confidence label**, it never withholds the artifact. The verifier is a **labeler,
not a gate** — the existing `[UNVERIFIED]` convention applies.

---

## 4. Consequences

**Positive.** The back half of the product already exists (§2.1), so the net-new surface is a capture
adapter, a connection model, a normalizer, five detectors and a URN namespace — the registry template's
sixth use, not a new pattern. The data model reuses a context that already has `ai_agent`,
`vendor_integration` and `vendor_log` in its enums, which means **no new bounded context and no
Finding-table migration**. Finding F5 is unavailable to any competitor without an asset graph, and we
have one. The tamper-evidence work (P3) fixes two of our own standing gaps before it ever points
outward, so it improves our posture even if the outward product stalls. And the primary capture path
is provisionable **by us, through an API**, rather than requiring the customer to follow a runbook.

**Negative / costs.** Capture is genuinely net-new and carries all the risk (§2.3) — nothing in our
substrate de-risks it. The primary mechanism's friction **depends on a fact we have not yet confirmed**
(Isaac's AI SDK major version), and the fallback is materially weaker (no tool semantics, no identity).
We inherit ADR 0021 D5's cost constraint: Trace Drains are Pro/Enterprise at **$0.50/GB on the
customer's bill**, which is a real objection from a cost-conscious buyer. The telemetry schema we
consume is **unversioned and unstable** — the split-out GenAI semconv repo has no releases, and
OpenInference is a competing convention, so a normalization layer is unavoidable maintenance. We
would hold a new class of highly sensitive data (agent behaviour against payment systems), which
raises our own breach blast radius and is why metadata-only is the default. And for shared-credential
estates — the likely case — **we are reconstructing attribution, not proving it**, which constrains
the product copy permanently.

## 4a. Non-goals

- **Not a new bounded context, and not a new findings store.** `provenance` + the Finding SSOT carry it.
- **No new write scope.** This ADR adds none; `open_draft_pr` and `components/response` remain the only
  write paths, both unchanged.
- **No content capture by default, ever.** Prompts and tool arguments are off unless separately consented.
- **Not forensic recovery.** Retention windows on the customer's side may be as short as one hour; we
  turn on accountability **going forward** and must never imply otherwise.
- **No claim of a cryptographically provable delegation chain** — RFC 8693 makes nested prior actors
  informational only.
- **No use of the word "provable"** in any customer-facing surface until D6 Tier 1 (including the
  customer-runnable verifier) has landed.
- **No auto-discovery of agents beyond the allowlist**, mirroring ADR 0021 D3's refusal.
- **Not red-teaming.** Probing a customer's AI endpoints is the sibling capability scoped in
  `AI_SECURITY_ARTICLE_MAPPING_2026-08-08.md` §6.1, and stays there.

---

## 5. Feature or company?

Henry's standing note (`STATE_AND_VISION.md` §1.1) is that three ideas in ~6 weeks each researched to
*"feature, not company"*, and that *"the next idea of this shape should cost an hour against this
page, not another research fleet."* So this answer is given directly.

### The verdict: **a FEATURE of Auto-Sec — and the strongest one available to us right now.** It is not a company.

**Why not a company.** The recording layer is already commoditized and consolidating:

- **Agnys** already sells **hash-chained agent audit logs at $49/mo, self-serve.** Their named
  weakness in our own competitive scan is *"records agents without **doing** anything."* If recording
  were the product, a $49/mo indie tool would already be it.
- **Vorlon** ($15.7M, Accel) already sells the **agent flight recorder** — as enterprise incident
  forensics.
- The consolidation rate in this segment over ~12 months is brutal: Protect AI → Palo Alto
  (~$650–700M), Prompt Security → SentinelOne ($250M), Aim → Cato, Lakera → Check Point, **Langfuse →
  ClickHouse**, Wiz → Google ($32B). A standalone agent-recording company is an acquisition target
  with a 12-month clock, not a durable business.
- The observability incumbents (Langfuse, LangSmith, Arize, Datadog LLM Observability) already hold
  the developer relationship and the same data.

**Why it is nonetheless a strong feature for us, and why the observability players are not the
competitor here.** Our own competitive scan already reached this and it survives the new research:

> "The observability layer is not a competitor for this, **by framing**. Langfuse, LangSmith, Arize
> and Datadog LLM Observability own the developers but frame everything as *debugging and evals* — an
> engineering tool, not an assurance product with an auditor as the reader. **Different buyer,
> different artifact, different retention guarantees.**"

Three things make it ours rather than theirs, and all three are structural:

1. **The join is the product, and we already hold one side of it.** Identity is absent by
   construction from every telemetry standard — accountability is a *join* between behaviour and
   credential provenance. An observability vendor holds behaviour. **We hold the asset graph, the
   Finding SSOT, the cloud/VCS/Vercel connections, and contextual risk** — the other side. Finding
   **F5** ("this agent can write to the bucket that this critical public-exposure finding is about")
   is unavailable to anyone without the graph. That is `STATE_AND_VISION.md` §1.1's moat sentence,
   replayed on agents.
2. **We already own the back half** (§2.1) — grants-vs-events modelling, approval gate, evidence
   provenance, board/triage/draft-PR remediation. A trace viewer would have to build all of it to
   compete; we would have to build only capture.
3. **"CIEM for agents" is an identified gap with no mature product.** Microsoft's own July 2026
   least-privilege-for-agents guidance is entirely **preventive** (tool binding, scoping, JIT) and
   **does not discuss granted-vs-used analysis for agents at all**. Meanwhile Stripe documents the
   granted-vs-used loop *as a manual procedure*. The retrospective, observed-usage narrowing of an
   agent's tool and credential surface is unoccupied, and every building block is programmatically
   accessible.

### What would have to be true for it to be a company

Stated so it can be tested rather than argued:

1. **Capture would have to become a standard we own or strongly shape** — e.g. the accountability
   layer MCP's SEP-2817/SEP-3004 are reaching for lands as something we authored or co-authored,
   rather than something the MCP spec absorbs. (Today both SEPs are unmerged and unsponsored — a
   window, but a narrow one, and Anthropic + Okta's XAA beta suggests the incumbents intend to own it.)
2. **The buying trigger would have to be regulatory and universal, not incidental** — every company
   running agents *must* produce an agent audit trail, on a deadline, to a named standard. EU AI Act
   high-risk enforcement (began 2026-08-02) and the NIST CAISI agent-standards initiative are the
   candidates; whether they bite for a US Series-A SaaS with 60 agents is the open question §7 puts
   to Henry.
3. **The evidence artifact would have to be portable and third-party-verifiable** — stapled inclusion
   proofs a customer's auditor accepts without trusting us (D6 Tier 2). That is what AIUC ($15M seed)
   is reaching for from the *standard* side while having **no operational evidence source** — which
   is exactly what we would be.

If all three became true, the company is "the agent evidence layer." **None of them is true today**,
and the standing rule is that we do not build for a hypothetical. So: build it as the feature, and
treat 1–3 as the tripwires that would change the answer.

---

## 6. Phasing — and an honest word about sequencing

**This does not outrank Tom's loops or go-live.** The customer-driven rule is explicit: does this move
Tom, Isaac, or the Sephora deployment forward *now*? Isaac's ADR 0021 P0 (a working Vercel Prowler
scan producing findings in his SSOT) is **already the named minimum bar for this same buyer**, is
smaller, and is closer to shipping. **This ADR queues behind it.** Every phase below awaits Henry's
explicit go.

There is also a real dependency to name up front: **`feature.provenance_graph` is dark today.**
Un-darkening it is shared prerequisite work that ADR 0009 D5 already wants for access-review evidence.

**The spine, which the phasing follows: identity → permissions → evidence.** Capture without identity
produces records that cannot be true about *which agent acted*; cryptography added later does not
repair that.

| Phase | Scope | Rough effort |
|---|---|---|
| **G0 — questions, zero code** | The Isaac questions in §7 — above all **which AI SDK version** (it swings the primary mechanism between "one line" and "sixty edits"), his Vercel plan tier (Trace Drains are Pro/Ent), and whether his agents share one Stripe key. Plus verify via the Stripe MCP whether request logs expose the acting key **programmatically**. | ~half a day |
| **P0 — the 1-week proof with Isaac: an inventory + ONE exposure statement** | Trace Drain provisioned via API (zero code change on his side), spans landing on an OTLP receiver, normalized into `ProvenanceActor`/`ProvenanceResource`/`ProvenanceEvent` rows under a decided `urn:agent:` namespace. Deliverable: *"here are your agents, here is which ones called Stripe and which called LLM providers, here is the one that has write access it used on Tuesday."* Metadata-only. Read-only. Flag-gated dark. **Exit criterion: one finding of class F2 or F3 on his real estate, with his consent.** | ~1 week |
| **P1 — the capability axis (the actual differentiator)** | The grant surface: MCP `tools/list`, Stripe restricted-key permissions, IdP scopes. `AccessGrant` rows populated. Detectors **F1** (granted-but-unused) and **F4** (capability drift) land, following AWS's three-field finding schema (`scope`, `unused actions`, `lastAccessed`) with a **stated window** and an archive/accepted-risk lifecycle. Board + `ROUTABLE_SOURCE_TYPES` + the specialist triage tool **in the same phase**. | ~1.5–2 weeks |
| **P2 — F5, the moat finding** | Join agent grants to the asset graph and the Finding SSOT by `asset_urn`: *"this agent can write to the resource this critical exposure finding is about."* Cheap **because the graph already exists** — this is the phase that makes the capability un-copyable by a trace viewer. | ~3–4 days |
| **P3 — evidence you can hand an auditor** | D6 Tier 1 in full (hash chain, canonical serialization, separate trust domain, **the customer-runnable verifier**, 12-month retention). **Do this inward first** — it fixes §2.4 gaps 1 and 3 on our own `DeepRunLog`/`EntityAuditLog`, improving our own posture, and only then points outward. | ~1 week |
| **P4 — remediation** | Narrowed tool manifest / narrowed restricted key as a **draft PR** where the grant lives in code (a new *patch strategy* on the ONE engine, never a second engine). Scope-revocation as a **proposed** response action only when there is a named customer asking — the response framework is a two-value enum today and this is a real build. | ~1 week+ |
| **Later / not now** | MCP server-side capture as a first-class source; the compliance pack (ADR 0009 lane); Tier 2 tamper-evidence; anything requiring a write scope. |

**Recommended cut: G0 → P0 → P1 → P2.** P0 alone is the validation moment and a clean stopping point
if Isaac's engagement dictates pace. **P3 is the phase that licenses the word "provable"** — until it
lands, the product copy says "logged and attributable", not "provable".

---

## 7. Open questions

### For Henry

1. **Sequencing.** ADR 0021 P0 (Vercel Prowler scan) is already Isaac's named minimum bar and is
   smaller. Confirm this ADR queues behind it — or, if agent accountability is now the *sharper*
   Isaac wedge, say so explicitly, because that is a change to the customer-driven ordering.
2. **`feature.provenance_graph` un-darkening** is a shared prerequisite with ADR 0009 D5. Should it be
   scheduled on its own merits (access-review evidence) rather than as a dependency discovered inside
   this build?
3. **Content capture policy.** D3 defaults to metadata-only, with prompts/tool-arguments off and
   separately consented. Is holding *any* customer prompt content ever acceptable, or should it be a
   permanent product boundary? (A permanent "we never hold your prompts" is a real differentiator
   against the observability vendors — and would also permanently close ADR 0021 D5's injection
   concern.)
4. **The "provable" claim.** Do you want P3 (Tier 1 + verifier) treated as a **gate** on the marketing
   word, as this ADR proposes? It is the difference between a defensible claim and the kind of
   overclaim an operator catches in five minutes.
5. **Feature-vs-company tripwires.** §5 names three conditions that would change the answer. Worth
   revisiting if the MCP audit SEPs find a sponsor, or if EU AI Act enforcement starts reaching
   US SaaS vendors through their enterprise customers' questionnaires.

### ⭐ The single question to ask Isaac

> **"When one of your ~60 agents charges a card through Stripe, whose credential does it use — and
> could you tell me which agent it was?"**

It is one question that tests everything at once: whether agents share a key (which decides whether we
can *prove* or merely *reconstruct*, and whether F3 is his headline finding), whether he has ever
needed to answer it (the buying trigger), and — from how fast he answers — whether this is a felt pain
or a hypothetical. **If he can answer it precisely, the product is much less interesting to him. If
he cannot, that hesitation is the sale.**

**The three follow-ups that unblock the build** (G0):
- **Which version of the Vercel AI SDK?** (v7 → one line; v6 → sixty edits. This single fact swings
  the primary capture mechanism.)
- **Which Vercel plan?** (Trace Drains are Pro/Enterprise at $0.50/GB **on his bill**.)
- **Consent to provision a read-only Trace Drain against one project** as the P0 validation moment.

### Could not verify (carried from the research notes)

- ⚠ **PCI DSS requirement numbering/wording** (10.3.2 / 10.3.4 / 10.5.1) — corroborated across QSA and
  vendor secondary sources only, **not** the PCI SSC primary document; older sources use the v3.2.1
  number 10.5.5 for what is now 10.3.4. **Confirm before any customer-facing use.**
- ⚠ **Whether Stripe exposes the acting restricted key per request *programmatically* via API** (the
  Dashboard per-key view is confirmed; API-level attribution is not). **A load-bearing claim depends
  on this — verify via the Stripe MCP.**
- Whether Vercel fetch spans ever carry request/response bodies (assumed metadata-only).
- Vercel's AI Gateway page states "AI SDK v5 and v6" while ai-sdk.dev documents 7.x as Latest — the
  vendor's own docs are inconsistent.
- All circulating agent over-privilege percentages (97% / 80% / 18%) trace to vendor blogs with no
  methodology. **Not used anywhere in this ADR, and must not be.**

---

## 8. Research grounding (claim → source)

All fetched 2026-08-09 unless noted. Fuller notes, rejected options and per-stream detail:
`docs/plans/AGENT_RUNTIME_ACCOUNTABILITY_RESEARCH_2026-08-09.md`.

| # | Claim | Source |
|---|---|---|
| R1 | **No principal / subject / credential / authorization attribute exists anywhere in `gen_ai.*`** — the conventions are content-and-performance conventions | https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/ · https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md |
| R2 | GenAI semconv **moved out** of the main repo (v1.42.0, 2026-06-12 deprecated + moved; v1.43.0, 2026-07-03 ships none of it); nothing is Stable; ⚠ **the new repo has no releases or tags** | https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/ · https://opentelemetry.io/docs/specs/semconv/gen-ai/ · https://github.com/open-telemetry/semantic-conventions-genai/releases |
| R3 | `execute_tool {name}` spans with `gen_ai.tool.name` / `.call.id`; content attributes (`gen_ai.input.messages`, `gen_ai.tool.call.arguments`) are **Opt-In** in the spec | https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md |
| R4 | **Vercel auto-instruments outbound HTTP as fetch spans "without needing any additional code changes"** | https://vercel.com/docs/tracing |
| R5 | Trace Drains: **OTLP/HTTP only**, any custom endpoint, per-drain sampling, **Pro/Enterprise at $0.50/GB**; **provisionable via the Drains REST API** | https://vercel.com/docs/drains/reference/traces · https://vercel.com/docs/drains · https://vercel.com/docs/rest-api/drains/create-a-new-drain |
| R6 | **AI SDK 7: `registerTelemetry(new OpenTelemetry())` once — "all AI SDK calls emit telemetry events by default"**; ⚠ **"both inputs and outputs are recorded" by default**; v6 and earlier use per-call `experimental_telemetry` | https://ai-sdk.dev/docs/ai-sdk-core/telemetry · https://langfuse.com/integrations/frameworks/vercel-ai-sdk |
| R7 | Vercel **Log** Drains carry **no outbound-call field**; runtime-log retention **Hobby 1h / Pro 1d / Enterprise 3d**, 30d only with paid Observability Plus | https://vercel.com/docs/drains/reference/logs · https://vercel.com/docs/logs/runtime · https://vercel.com/docs/observability/observability-plus |
| R8 | AI Gateway logs carry model/provider/tokens/cost/status and **the originating API key**, but **no content and no tool calls**; `ai-reporting-user` / `ai-reporting-tags` headers stamp context **"without modifying application code"** | https://vercel.com/docs/ai-gateway/observability-and-spend/logs · https://vercel.com/docs/ai-gateway/observability-and-spend/custom-reporting |
| R9 | MCP rev **2026-07-28**: `logging` is server→client and **deprecated** (SEP-2577) and MUST NOT carry credentials/PII; **no audit schema, no tool-call recording standard, no correlation id, no retention model**; SEP-2817 / SEP-3004 unmerged and unsponsored | https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/logging · https://modelcontextprotocol.io/specification/2026-07-28/deprecated · https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2817 |
| R10 | MCP servers are **OAuth 2.1 resource servers** and "MUST validate that access tokens presented to them were specifically issued for their use" — **the only protocol-verified caller identity**; `clientInfo` is self-reported and **explicitly not for security decisions**; tool annotations **MUST be considered untrusted** | https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization · https://modelcontextprotocol.io/specification/2026-07-28/basic/index#meta · https://modelcontextprotocol.io/specification/2026-07-28/server/tools |
| R11 | `tools/list` + `notifications/tools/list_changed` make **capability-surface drift detectable in real time** | https://modelcontextprotocol.io/specification/2025-06-18/server/tools |
| R12 | **"If the service account is authenticated with a service account key, there is no reliable way to tell who used the key"** — and shared accounts break tracing activity to the correct application | https://docs.cloud.google.com/iam/docs/best-practices-service-accounts |
| R13 | **Entra Agent ID is GA (April 2026)**; blueprint/instance model; ⭐ **`agentType` + `blueprintId` stamped onto the EXISTING audit schema** rather than a parallel log; sponsor role + orphan-prevention lifecycle | https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id · https://learn.microsoft.com/en-us/entra/agent-id/key-concepts · https://learn.microsoft.com/en-us/entra/agent-id/sign-in-audit-logs-agents |
| R14 | RFC 8693 impersonation-vs-delegation; ⚠ **"Prior actors identified by any nested `act` claims are informational only"** → no "cryptographically provable chain" claim | https://www.rfc-editor.org/rfc/rfc8693.html |
| R15 | `draft-ietf-oauth-identity-chaining-17` (2026-07-19), Standards Track WG doc — a profile of RFC 7523 + 8693, **never mentions agents** | https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-chaining/ |
| R16 | Okta **Cross App Access** (Identity Assertion Authorization Grant); OIN availability from **Aug 2026**, Auth0 B2B early access end of **July 2026**; **Anthropic's beta includes Okta as featured IdP** for Claude↔MCP access | https://www.okta.com/solutions/cross-app-access/ · https://www.okta.com/newsroom/press-releases/okta-announces-cross-app-access-partners/ |
| R17 | **Auth0 for AI Agents GA 2025-11-19** — Token Vault + **CIBA async human-in-the-loop authorization**; ⚠ the GA material does **not** describe per-agent identity, attribution, or audit trails | https://auth0.com/blog/auth0-for-ai-agents-generally-available/ |
| R18 | SPIFFE gives workload identity but **cannot express "acting on behalf of user Y, scoped, time-bounded, with an audit record"**; WIMSE is addressing it | https://www.idenhq.com/en/playbooks/spiffe-answers-why · https://www.hashicorp.com/en/blog/spiffe-securing-the-identity-of-agentic-ai-and-non-human-actors |
| R19 | ⭐ Stripe: **"always use restricted API keys … especially when giving a key to an AI agent"**, **"use one restricted key per service or use case"**, request logs are **per-key**, and the documented permission-narrowing procedure **is manual CIEM** | https://docs.stripe.com/keys/restricted-api-keys · https://docs.stripe.com/keys.md · https://docs.stripe.com/development/dashboard/request-logs.md |
| R20 | Stripe **Activity Logs retain 6 months** — against PCI's 12-month requirement | https://docs.stripe.com/activity-logs · https://docs.stripe.com/changelog/dahlia/2026-04-22/programmatic-access-to-activity-logs |
| R21 | AWS IAM Access Analyzer **unused-permissions finding = `serviceNamespace` + `actions[]` + `lastAccessed`**, with active/resolved/**archived** lifecycle and archive rules; unused-access analysis is **separately billed** | https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-findings.html · https://docs.aws.amazon.com/access-analyzer/latest/APIReference/API_UnusedPermissionDetails.html |
| R22 | ⚠ **Microsoft Entra Permissions Management is retired** (support ended 2025-11-01); the **Permission Creep Index** metric survives inside Defender for Cloud CIEM | https://techcommunity.microsoft.com/blog/microsoft-entra-blog/important-change-announcement-microsoft-entra-permissions-management-end-of-sale/4399382 · https://learn.microsoft.com/en-us/entra/permissions-management/ui-dashboard |
| R23 | GCP role recommendations compare granted vs used over a **90-day window** (30/60 configurable) and **predict future need** to avoid revoking low-cadence permissions | https://docs.cloud.google.com/policy-intelligence/docs/role-recommendations-overview |
| R24 | ⭐ Microsoft's **"Least privilege for AI agents"** (2026-07-16) — agents as first-class principals + **tool binding**, and it is **entirely preventive: no granted-vs-used analysis for agents** | https://www.microsoft.com/en-us/security/blog/2026/07/16/least-privilege-for-ai-agents-identity-access-and-tool-binding/ |
| R25 | ⭐ CloudTrail integrity validation — SHA-256 + SHA-256/RSA, **hourly digests each carrying the previous digest's signature**, **digests in a separate folder** from logs, and the ability to **positively assert no logs were delivered in a period**; customer-runnable verifier | https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html |
| R26 | ⚠ **Amazon QLDB retired (support ended 2025-07-31)**; AWS recommends Aurora PostgreSQL, which **does not provide cryptographic verifiability** | https://www.infoq.com/news/2024/07/aws-kill-qldb/ · https://techcommunity.microsoft.com/blog/azuresqlblog/moving-from-amazon-quantum-ledger-database-qldb-to-ledger-in-azure-sql/4246237 |
| R27 | Sigstore Rekor — append-only Merkle transparency log with **inclusion and consistency proofs**, clients can **"staple"** a proof beside the artifact; Sigstore runs a **free RFC 3161 TSA** | https://docs.sigstore.dev/logging/overview/ · https://github.com/sigstore/timestamp-authority |
| R28 | S3 Object Lock **Compliance mode: "no one can modify the object lock settings, not even the root user"**; Governance mode is bypassable with a permission | https://aws.amazon.com/about-aws/whats-new/2018/11/s3-object-lock |
| R29 | Crosby & Wallach, *Efficient Data Structures for Tamper-Evident Logging* — the canonical academic reference for hash-chain vs Merkle-tree audit logs | https://static.usenix.org/event/sec09/tech/full_papers/crosby.pdf |
| R30 | ⚠ **PCI DSS v4.0 Req 10** (10.3.2 log protection, 10.3.4 FIM on audit logs, **10.5.1 12 months / 3 hot**) — **corroborated across QSA and vendor secondary sources only; NOT fetched from the PCI SSC primary document.** Confirm before customer-facing use | https://explore.kirkpatrickprice.com/videos/pci-v4-0-10-5-1-retain-audit-log-history-for-at-least-12-months · https://cdn2.qualys.com/docs/mktg/qualys-fim-coverage-pci-dss-4.0.pdf |

**In-repo sources:** `docs/plans/AI_SECURITY_ARTICLE_MAPPING_2026-08-08.md` (§5 Lens-A adopt list,
§6 Lens-B roadmap) · `docs/competitive/LANDSCAPE_2026-08.md` §5 (Vorlon / AIUC / Agnys; the
consolidation list; the observability-framing conclusion) · `docs/product/STATE_AND_VISION.md` §1.1
(exposure-anchored rule, moat sentence, feature-not-company standing note), §2.1 (Tom's gap #5),
§2.2 (Andrea's gap #4), §4.4 ("Traces: none for customer workloads") ·
`docs/architecture/ARCHITECTURE_REVIEW_2026-08-09.md` §1.1 (the unbuilt-bet finding) ·
`docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md` §3.4 (the inward twin of this vocabulary) ·
ADR 0004, 0008, 0009, 0010, 0013, 0017, 0019, 0021.
