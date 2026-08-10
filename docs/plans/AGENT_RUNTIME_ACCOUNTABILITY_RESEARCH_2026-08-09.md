# Agent Runtime Accountability — working research notes (2026-08-09)

**Status:** WORKING NOTES for ADR 0023. Not a decision doc. Committed incrementally so research is
never lost mid-session. Folded into the ADR as it firms up; the ADR is the deliverable.

**Question being scoped (Henry's words):** *"what are a customer's AI agents actually doing, with
what tool access, under what identity, logged and provable after the fact."*

**Concrete customer:** Isaac — ~60 AI agents in production doing client-facing work, handles card
data via Stripe, no security team, ships fast, hosted on Vercel.

**HARD framing rule (Henry's prior conclusion, three ideas died on it):** value must be
**exposure-anchored, never absence-anchored**. Every capability must terminate in a concrete
provable exposure statement ("this agent holds write access to Stripe and used it Tuesday under
this identity — here's the trace"), never in an absence statement ("you lack visibility").

---

## 0. Provenance of this doc / relationship to prior research

`docs/plans/AI_SECURITY_ARTICLE_MAPPING_2026-08-08.md` (read in full, 2026-08-09) scoped two
ADJACENT things. This work is neither, and must not duplicate them:

| Prior item | What it is | Relationship to this ADR |
|---|---|---|
| Lens-B #1 — AI-SPM red-teaming pillar (Garak engine behind `ScannerPort`) | **Attack** the customer's AI endpoints for injection/jailbreak/leakage | **Sibling.** Different verb (probe vs observe), different data (synthetic attacks vs real production actions). Shares the `ScannerPort`/Finding SSOT landing zone. |
| Lens-B #2 — shadow-AI discovery over customer logs (LLM-egress in CloudTrail/app logs, rides LogSourcePort) | **Discover** unsanctioned AI usage | **Prerequisite / sub-capability.** The same log-derived signal is the *fallback capture path* here. Discovery answers "an agent exists"; this ADR answers "what did it do, as whom, with what grants." Discovery alone is ABSENCE-anchored (the trap) — this ADR is what makes it exposure-anchored. |
| Lens-B #3 — customer AI governance pack (comply lens, ADR 0009) | Inventory + risk register + NIST/ATLAS control mapping | **Downstream consumer.** Needs the inventory + evidence this ADR produces. Cannot be built first. |
| Lens-A adopt #2 — AI-telemetry security detections over OUR OWN telemetry | Detectors over DeepRunLog etc. feeding Finding SSOT | **Dogfood of this ADR's detection layer.** Same detector vocabulary, pointed inward first. |

Verdict to state in the ADR: **this ADR supersedes nothing; it is the sibling of Lens-B #1, the
completion of Lens-B #2, and the prerequisite of Lens-B #3.**

## 1. Bookkeeping / ground truth (verified 2026-08-09)

- Newest ADR on `origin/main` = **0022** (`0022-scan-output-artifact-channel.md`).
- **0014 is CLAIMED** by open PR #230 (`docs/adr-hud-layout`, "0014 customizable persona-templated
  HUD layout") — it is a gap in `main` but must NOT be reused.
- => this ADR takes **0023**.
- Open PRs at start: #305 (suppressed-card archival), #230 (ADR 0014), #49, #48, #47. Several
  active worktrees (artifact channel, throttle hardening, contrast fix) — all code lanes; this is
  docs-only, no collision.
- Worktree: `/Users/henrywanjala/Desktop/auto-sec/worktrees/adr-agent-accountability`, branch
  `docs/adr-agent-accountability`, off `origin/main` @ `8b6fe1f`.

## 2. Research streams (status tracker)

| # | Stream | Status |
|---|---|---|
| A | Map OUR substrate in code (DeepRunLog/AIAction/sign_off/EntityAuditLog/Langfuse/response-actions/board provenance) | pending |
| B | Map OUR ingestion spine (LogSourcePort, Finding SSOT, asset graph, AssetUrn, ScannerPort registry) | pending |
| C | Capture problem — OTel GenAI semconv / gateway / logs / SDK callbacks / MCP, ranked for Isaac | pending |
| D | Agent identity standards (Entra Agent ID, Okta/Auth0, SPIFFE, token exchange) | pending |
| E | Tool-access surface — CAN-do vs DID-do | pending |
| F | Tamper-evidence — what "provable" honestly requires | pending |
| G | Standards / buying trigger (ATLAS agentic, OWASP LLM06/08 + ASI, NIST AI RMF, EU AI Act logging, CAISI) | pending |
| H | Competitive (Zenity/Noma/WitnessAI/Lakera/Prompt Security/PANW-Protect AI/Wiz vs Langfuse/LangSmith/Arize/Braintrust) | pending |

## 2.5 In-repo grounding already gathered (2026-08-09)

### This ADR is the sanctioned "now build it" moment

`docs/architecture/ARCHITECTURE_REVIEW_2026-08-09.md` §1.1 correction #1 states it outright:

> "Provenance/audit of **our own agents** is BUILT and is a strength (agent service principal
> SEE-201, per-call `DeepRunLog` + Langfuse, `AIAction` rows, sign_off gates, the board-provenance
> HARD rule) … Monitoring the **customer's** agents (Isaac's ~60: 'what did MY agents do, under what
> identity') is the genuinely unbuilt bet. **There is no ADR for it** — it is deliberately
> written-down-not-built … **When you decide to build it, that's the moment it gets an ADR.**"

So: the review independently confirms both halves of the thesis — our substrate is real, the outward
version is unbuilt — and pre-authorizes this ADR as the artifact.

### ADR 0021 (Vercel posture provider) is the closest precedent — reuse, do not re-derive

ADR 0021 already did the Isaac/Vercel grounding pass. Load-bearing facts to inherit rather than
re-research:

- **Isaac confirmed on Vercel (2026-08-09)**, ~60 agents, Stripe card data, no security team. ADR
  0021 §"customer-driven work" + OQ1.
- **`VercelConnection` (D2)** — token-shaped connection mirroring `VcsConnection`: workspace FK,
  `team_id`, `team_slug`, `token_ciphertext` via the ONE integrations Fernet envelope
  (`components/integrations/infrastructure/adapters/secret_envelope.py`), a `credential_kind`
  discriminator (`token` | `oauth_integration`), `verify()` against `GET /v2/user`, health fields,
  Settings ▸ Integrations panel. **If agent capture needs a Vercel credential, it rides this row —
  it must not mint a second Vercel connection model.**
- **Consent stance (D3):** the connection names ONE team; Prowler's "no team ⇒ auto-discover and
  scan every team the user belongs to" is explicitly called **"a consent violation in our model."**
  That is the consent precedent for this ADR: enumerate exactly what was named, never what the
  token can reach.
- **Read-only precedent** (architecture review §1): AWS = customer-side role with
  `ViewOnlyAccess`/`SecurityAudit` + ExternalId (confused-deputy protection), STS AssumeRole vended
  per run; Vercel = read-only **Viewer-role** token; VCS write is used **only** by `open_draft_pr`,
  never merges. `components/response` is the single named write exception (propose→approve→execute,
  boto3 `DryRun` default) and its write scopes are "a separate, explicitly-consented role add-on,
  never folded into the audit role."
- **Flag-gating pattern (D6):** `feature.<x>` sibling flag, seeded in `seed_feature_flags`, listed in
  `PROD_DISABLED_FLAGS`, un-darkened per workspace; fail closed (missing ⇒ off). Never reuse an
  adjacent pillar's flag — "a workspace opted into AWS CSPM has not consented to a Vercel scan
  surface." Same logic applies doubly to agent telemetry.
- **The board/triage seam is a proven ~1-day recipe, "fifth use" as of ADR 0021 D4:** a `_SOURCE_BOARD`
  entry + a `ROUTABLE_SOURCE_TYPES` entry + a triage tool **in the same phase**, because
  "routable without a tool is a silent no-op."
- **`AssetUrn.canonical(source_system, ref)`** takes the provider as a free string and already
  namespaces `urn:vercel:<ref>` (`components/shared_kernel/domain/security.py:210-226`);
  `CloudAssetEntity.provider` is a plain `str`. So a new `urn:` namespace costs nothing in the
  kernel — the discipline is that the namespace must be *decided*, never defaulted (ADR 0021 D1's
  "silently poisoned asset graph" trap: a finding entering the SSOT wearing the wrong URN namespace
  "would not fail loudly; it would succeed and lie").

### ⚠ The constraint that reshapes the capture decision: Vercel logs are already a NO

ADR 0021 **D5 ruled Vercel log ingestion out of scope**, with evidence:

- **No `logs` integration scope exists** — runtime logs 403 even with every scope granted.
- **Log Drains are Pro/Enterprise-gated at $0.50/GB on the customer's bill.**
- **Drain payloads are attacker-authored strings** (`proxy.path`, `userAgent`, `message`) entering
  the AI triage pipeline — "the first ingest source where an unauthenticated internet client writes
  the LLM's input."

Re-entry requires ALL of: a paying Pro+ customer asking; an injection-fence test passing; the
`process_records()` extraction + workspace-keyed ingest + nullable-connection rollup FKs landed; and
per-source byte/rate caps + `clientIp`/JA3 retention-purge designed.

**Implication for this ADR (important):** the generic "log-based reconstruction rides LogSourcePort"
fallback is *much weaker for Isaac specifically* than it looks on paper. His agents run on Vercel;
Vercel runtime logs are not cheaply reachable, and the drain path is already refused. Any fallback I
recommend must either (a) target a log surface Isaac actually has that ISN'T Vercel drains (e.g. his
LLM provider's own usage/export APIs, his Stripe API logs, an AWS account if he has one), or
(b) explicitly inherit D5's re-entry conditions. Do not casually re-open a door ADR 0021 closed.

### Other in-repo anchors

- **`docs/competitive/LANDSCAPE_2026-08.md`** — current market scan; its stance on this capability is
  "write it down, do not build it yet." `docs/product/STATE_AND_VISION.md` §2 is partly superseded by it.
- **`STATE_AND_VISION.md` §1.1** — the moat sentence and the design instruction this ADR must obey:
  *"write exposure-anchored rules, never absence-anchored ones"* — match the missing guard **joined
  to** reachability. Converts a precision problem into a filter problem; the filter is the moat.
  Also the standing note: three ideas in ~6 weeks all researched to *feature, not company* — "the
  next idea of this shape should cost an hour against this page, not another research fleet." This
  ADR must answer feature-vs-company explicitly and cheaply.
- **`STATE_AND_VISION.md` §4.4:** "**Traces: none for customer workloads** (Langfuse traces *our own
  agents* — a different concern). This is the net-new pillar." Confirms no existing home.
- **§4.5:** response actions are propose → approve → execute → rollback with dry-run + credential
  vending; **one** live action (`REVOKE_SG_INGRESS`); approve-to-execute orchestration is minimal.
  Any "revoke the agent's scope" remediation must be honest that this rail is thin today.
- **Tom's signal (§2.1 gap #5):** "LLM / agent-trace observability in the HUD — his home turf; eval
  the whole agent *trace*, replay provenance if something escapes the sandbox." A **second** named
  operator already asked for this. He cross-referenced Datadog LLM Observability + Langfuse.
- **Andrea's signal (§2.2 gap #4):** "Shadow-AI monitoring + AI-governance evidence — *'show how many
  users talk to known AI platforms — bonus if you can enforce.'*" Third named operator, compliance lens.

### The competitive scan for THIS bet already exists in-repo — and says it is unoccupied

`docs/competitive/LANDSCAPE_2026-08.md` §5 ("Segment 4 — AI security & governance: the horizon
bet") is dated 2026-08-03 and scans exactly this capability. Verdict quoted:

> "Consolidating at machine speed, entirely at enterprise altitude, and **the specific bet Auto-Sec
> would make is unoccupied**."

- **Consolidation (~12 months):** Protect AI → Palo Alto (~$650–700M, Jul 2025); Prompt Security →
  SentinelOne ($250M, Sep 2025); Aim → Cato (Sep 2025); Lakera → Check Point (2025); **Langfuse →
  ClickHouse (Jan 2026)**; Wiz → Google ($32B, Mar 2026).
- **Independents raising on "agent security":** Noma $100M Series B; **Zenity $125M Series C
  (2026-08-03)**; Straiker $64M Series A (Jun 2026).
- **The three nearest players, each holding exactly one fragment:**

  | Player | Has | Missing |
  |---|---|---|
  | **Vorlon** ($15.7M, Accel) | The agent flight recorder | Sold as enterprise incident forensics; no compliance output, no security work |
  | **AIUC** ($15M seed) | The assurance *standard* + audit + insurance | Point-in-time certification with **no operational evidence source** |
  | **Agnys** (no disclosed funding) | **Hash-chained agent audit logs, $49/mo, self-serve** | Records agents without *doing* anything; indie/unfunded |

- **Regulatory timing:** EU AI Act high-risk enforcement began **2026-08-02**; NIST opened an AI
  Agent Standards Initiative Feb 2026; "agent audit trail" language appearing across roadmaps.
- **Key framing conclusion (reuse verbatim):** *"The observability layer is not a competitor for
  this, by framing.* Langfuse, LangSmith, Arize and Datadog LLM Observability own the developers but
  frame everything as *debugging and evals* — an engineering tool, not an assurance product with an
  auditor as the reader. Different buyer, different artifact, different retention guarantees."
- **Our unfair structural claim:** *"Auto-Sec … is itself a deep-agent system already carrying
  sign-off gates, tool-risk tiers, a kill switch, DeepRun telemetry and an audit trail. **The
  dogfooding is the proof.**"* — this is the thesis this ADR is asked to confirm or refute, already
  asserted independently.
- **The converged white space (§7):** *"Do the security work for a company with no security staff,
  and let audit-grade evidence accumulate as the byproduct."*

**Three takeaways that constrain the ADR:**
1. **Agnys is the direct-competitor datapoint** — hash-chained agent audit logs at $49/mo self-serve
   already exists. So "record agent actions with tamper-evidence" is *not itself* differentiated.
   Their named weakness — "records agents without **doing** anything" — is precisely the
   exposure-anchored gap. Our differentiator must be the join to the graph + the remediation loop,
   never the recording.
2. **Vorlon proves the "flight recorder" framing sells** — but at enterprise altitude, as forensics.
3. **Langfuse being acquired by ClickHouse (Jan 2026)** is directly relevant: it is in our stack, and
   its trajectory is data-infrastructure, not assurance. Verify this with the competitive research
   stream before relying on it.

### Earlier internal framing: `SECURITY_POSTURE_VISION_2026-07-20.md` §3.4

Named the AI-governance persona's questions almost exactly as Henry frames them now: *"What is the
AI itself doing? Which roles did it use? Who granted it which permissions? Can we kill it right
now?"* — but scoped **inward** (`ai_governance_agent` dogfooding our own fleet: tool usage by risk
tier, HITL approvals granted/denied, capability grants, credential scopes, MCP/tool inventory, kill
switch). That is the inward twin of this ADR. The vocabulary is already designed; this ADR points
it outward.

## 3. Findings — Stream A (our substrate)

_pending — code-mapping agent running_

## 4. Findings — Stream B (our ingestion spine)

_pending — code-mapping agent running_

## 5. Findings — Stream C (the capture problem)

_pending_

## 6. Findings — Streams D–H

_pending_

## 7. Open questions / could-not-verify

_pending_
