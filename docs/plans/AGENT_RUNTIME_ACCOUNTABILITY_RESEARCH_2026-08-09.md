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

## 3. Findings — Stream A (our substrate) — COMPLETE

### 3.0 The thesis verdict: CONFIRMED, but only for the back half

The claim under test was *"turning our own accountability substrate outward is a much shorter path
than building AI-SPM from scratch."* The code map splits our substrate cleanly in two, and the
answer differs per half:

| Half | Components | Verdict |
|---|---|---|
| **The ledger / governance half** | `provenance` graph (`ProvenanceActor`/`Resource`/`AccessGrant`/`Event`), `EntityAuditLog`, `sign_off` kernel, `response` action ledger, Finding SSOT, board-provenance JSON, the WS-redaction + owner-only authz contract | **Source-agnostic today.** Ports outward with little or no schema change. `SourceSystem` already enumerates `aws/okta/google_workspace/slack/github`; `ActorType` already has `ai_agent` and `vendor_integration`; `ProvenanceEvent.Origin` already has **`vendor_log`**. The `sign_off` kernel is a pure ABC + value-object kernel with **zero** runtime assumptions. |
| **The capture half** | `DeepRunLog` writer, the `@tool(risk=…)` gate, the Langfuse callback, the AI service principal | **Structurally ours-only.** Does NOT port. |

**So the honest answer is: we get the storage, correlation, evidence, approval and remediation
back-end essentially free — and the capture front-end is genuinely net-new and is the entire risk of
the project.** That is still a large head start (it is most of a product), but the ADR must not claim
the hard part is done. The hard part is §5.

### 3.1 DeepRun / DeepRunLog — `infrastructure/persistence/ai/agents/models.py`

- **`DeepRun`** (L344–377): `thread_id(unique)`, `plan_id`, **`user` FK(CASCADE) ← the principal**,
  `workspace` FK(SET_NULL), `status`, `state(JSON — plan, goal, usage)`, `checkpoints(JSON)`,
  `last_error`, timestamps. Indexes on `thread_id`, `plan_id`, `(status, updated_at)`.
- **`DeepRunLog`** (L380–419): `deep_run` FK(CASCADE), `event_type` (`run_started`, `worker_started`,
  **`tool_observation`**, `tool_log`, `tool_progress`, `run_failed`, `llm_call`), `status`,
  `agent_type`, **`tool_name`**, **`payload(JSON)`** — for a tool observation
  `{tool_input, tool_output, truncated_input, truncated_output}` — plus `system_prompt`,
  `user_prompt`, `llm_response`, `model_used`, `prompt_tokens`, `completion_tokens`, `latency_ms`,
  **`cost_usd(10,6)`** computed at write time, `created_at`.
- Tool IO truncated at `_TOOL_OBSERVATION_MAX_CHARS = 4000` with explicit truncation flags
  (`base.py:2179–2264`).
- **Append-only by convention, not by constraint.** Only production writer is
  `DeepRunLog.objects.create(...)` in `components/agents/infrastructure/gateways/deep/logging.py:29`;
  no `.update(`/`.delete(` outside tests. But: **no `editable=False`, no DB trigger, no hash chain,
  no signature**, and rows CASCADE-delete with `DeepRun` → with `User`. No retention/purge job.
- **Principal lives on the parent `DeepRun.user`, not on the log row.**
- **Coupling: HIGH.** `log_deep_event(thread_id, …)` resolves the run by an **in-memory
  `thread_id`** and silently no-ops if absent; the observation writer reads LangChain's
  `intermediate_steps` tuples directly. The REST surface (`DeepRunViewSet`,
  `components/agents/api/controller.py:1594`) is **read-only — there is no ingest endpoint.**
  The *schema* is source-agnostic; pointing it outward is a `RunEventIngestPort` problem. The one
  real obstacle is the `DeepRun.user` FK into `CustomUser`.

### 3.2 ⚠ `AIAction` NO LONGER EXISTS — correct the premise

The task brief (and CLAUDE-adjacent memory) refers to `AIAction`; it was **deleted in Phase 5 of the
Agents-as-Teammates migration**. Evidence: `components/agents/infrastructure/services/actions_service.py:1–26`
(docstring is the migration note; the class keeps the legacy name `AIActionService` but only manages
teammate lifecycle); `base.py:1982–1985` — *"nothing writes to the deleted AIAction table"*;
`infrastructure/persistence/project/models.py:248–257` records which `Task` fields absorbed
`AIAction.summary`/`.payload`/`.context`.

**An "action" today = a `project.Task` row with `source_type="ai.<action_type>"`,** created by
`persist_finding_as_task` (`specialist_persistence_service.py:65–219`). `metadata` carries
`agent_type, detector, action_type, severity, impact_score, ai_headline, ai_narrative,
idempotency_key, provenance{…}, triage{status}, payload{…}, context{…}`. Idempotency key is
`(workspace_id, source_type, metadata.idempotency_key)`.

**Named gap:** there is **no FK from an action to the DeepRun that produced it** — the only link is
`Task.metadata["run_telemetry"]["source_thread_id"]`, stamped post-hoc by
`stamp_run_telemetry_on_findings` (`_finding_processing.py:395–456`) via a **heuristic match**
(`metadata.triage.agent == specialist AND updated_at >= since`). For an accountability product whose
whole claim is "here's the trace", a heuristic action→run link is a real weakness worth naming.

### 3.3 WS redaction + owner-only run detail — the read-authz contract

- Redactor: `components/agents/infrastructure/adapters/deep_run_realtime_signal_bridge.py`.
  **`_ALLOWED_PAYLOAD_KEYS` is a hard allowlist of six: `progress_percent, current, total, severity,
  task_id, plan_id`.** Defence in depth: `_MAX_ALLOWED_STR_LEN = 100` — an allowlisted key holding a
  >100-char string, or any non-scalar, is dropped. Explicitly redacted: `tool_input`, `tool_output`,
  `message`, `question`, `error`, `telemetry`. Publish deferred via `transaction.on_commit`.
- Authz: `_is_run_owner` (`components/agents/api/controller.py:157–169`) — **only the user who
  started the run, plus `is_staff`**; enforced on `retrieve` and `events`. Teammates get
  `DeepRunSummaryView` (`deep_run_query_port.py:100–131`), which **deliberately omits `goal`**
  because it is the raw user prompt; `DeepRunSnapshotView` carries `goal`/`last_error` and is
  owner-only.
- Test: `components/agents/tests/integration/test_deep_run_ws_envelope_redaction.py` — 4 cases,
  asserting on the serialized JSON so a leak anywhere in the envelope fails.
- **Coupling: LOW — operates on stored rows; works unchanged over externally-reported data.** This is
  a genuine asset: a multi-tenant, least-disclosure read contract for agent traces already exists and
  is tested. (Matches the standing memory: run detail is OWNER-ONLY; never re-widen.)

### 3.4 `sign_off` — the strongest "point it outward" candidate

- State machine (`domain/value_objects/review_state.py`): `PENDING → {APPROVED, CHANGES_REQUESTED,
  REJECTED}`; `CHANGES_REQUESTED → {PENDING, REJECTED}`; **`APPROVED → {PENDING}`** (an edit after
  sign-off re-opens review); `REJECTED` terminal.
- `RiskBand` GREEN|AMBER|RED governs **friction, never bypass**. `SignOffTarget(audience, high_stakes)`
  where `Audience = INTERNAL_SELF|INTERNAL_TEAM|EXTERNAL`; `.escalates` bumps the band.
- **Anti-rubber-stamp receipts** (`reviewer_receipts.py`): `FigureCheck(claim_text, stated_value,
  source_value, verified, source_ref)`, `ClaimProvenance(claim_text, source_record_ref, grounded)`,
  `VoiceFlag`, aggregated by `ReviewerReceipts.has_flags/has_contradictions/is_clean`.
- `sign_off_service.approve()` **raises `SignOffError` if RED without a non-empty `override_reason`**
  — forced justification. Every transition calls `SignOffAuditPort.record(...)` → `EntityAuditLog`
  under `entity_type="signoff.<artifact_type>"` (audit failure is logged and swallowed, never breaks
  the decision).
- The teeth: `require_approved(artifact_type, artifact_id)` raises `NotApprovedError` unless APPROVED.
- Queue projects onto the Kanban via `materialize_signoff_tasks.py` as
  `source_type="ai.sign_off_pending"`.
- **Coupling: NONE — pure ABC + VO kernel.** ⚠ **But the registry ships EMPTY**
  (`sign_off_registry_provider.py:41–46` — "Phase 2-5: register per-context adapters here"). So the
  kernel is real and unused; the ADR must not describe it as a live gate today.

### 3.5 Board provenance — three writers, one JSON structure

All at `project.Task.metadata["provenance"]` — **not a separate table**:
1. **Creation** (`specialist_persistence_service.py:151–168`): `created_by_kind, detector,
   assigned_specialist, source_type, created_at, confidence, impact_score, events[]`.
2. **Acting** (`_finding_processing.py:280–296`) — inside `select_for_update(of=("self",))` with a
   status re-check so overlapping cycles can't double-act; appends
   `{"actor": "agent:<slug>", "action": …, "at": …, "moved": true}` plus `last_handled_by/at` and a
   `metadata.triage` block (`status, agent, triaged_at, actions[], suggested, verification,
   verification_gap, needs_human, no_fix_reason`). The verifier is **a labeler, not a gate** —
   ungrounded gets ONE re-advise then ships labeled `unverified`.
3. **Draft PR** (`record_finding_draft_pr_repository.py:40–110`): writes
   `metadata.payload.draft_pr{url, repo, branch, opened_by, opened_at, verification,
   verification_gap, path, diff, change_summary}` and appends
   **`{"actor": "agent:<agent> via user:<human>", …}`** — ⭐ **the dual-principal actor string is the
   closest thing in the codebase to a delegated-identity record**, and is directly the shape Stream D
   (agent-acting-on-behalf-of-human) needs. Backfill writes `"system:autosec"` and **can never
   rewrite identity facts or upgrade a confidence label**.
- Canonical path + bound live in the **port** (`record_finding_draft_pr_port.py`):
  `DRAFT_PR_METADATA_PATH`, `DRAFT_PR_DIFF_MAX_CHARS = 12_000`.
- Projected into the `provenance` context by `ai_backfill_service.py`, which **parses `agent:<slug>`
  actor strings into `ProvenanceActor(actor_type="ai_agent", source_system="ai")`** and each event
  into a `ProvenanceEvent` keyed idempotently on `<task_id>:<index>`.

### 3.6 EntityAuditLog + the provenance graph

- `EntityAuditLog` (`infrastructure/persistence/audit/models.py`): `id(UUID, editable=False)`,
  `workspace` FK(CASCADE, null), `content_type` FK(PROTECT) + `object_id` + GenericFK, `field_name`,
  `previous_value(JSON)`, `new_value(JSON)`, `actor` FK(SET_NULL, null — nullable for system writes),
  `reason`, `created_at`. Four indexes. **New entity type or tracked field = zero schema change.**
- **Immutability is documented convention, not enforcement**: module docstring says "Append-only… add
  a compensating row rather than rewriting history"; the repository exposes only `record` + reads.
  But **no DB trigger, no WORM, no hash chain**, and `workspace` is CASCADE so deleting a workspace
  deletes its audit trail. **No retention policy anywhere.**
- Read authz: `IsAuditWorkspaceMember` — deliberately **membership, not admin** ("a read surface for
  every operator in the tenant, including the read-only auditor persona"); requires explicit
  `workspace_id` (missing → 400, unknown → 403 so existence doesn't leak).
- `provenance` models per §4.0. `ProvenanceEvent` docstring: *"Action edge (Actor → Resource) — the
  **actual**. Append-only."*; `metadata` docstring names *"ip, session id, request id, **tool**"*;
  unique `(workspace, origin, origin_id)` = idempotent projection. **`Origin = audit_log | ai_action |
  identity_session | vendor_log`.** Backfills exist for three internal origins; **a fourth for
  external agents is the same pattern.**
- API is read-only, gated by `feature.provenance_graph` + `HasWorkspaceMembership`: graph overview,
  vendor blast-radius, hall-tree, access-review, **least-privilege**.

### 3.7 Langfuse / `TracingPort` — ⚠ not part of the queryable substrate

`components/agents/application/ports/tracing_port.py`: `is_available()`,
`get_langchain_callback(*, agent_id, user_id, session_id)`, plus default-no-op
`trace_conversation` / `trace_llm_call` / `trace_retrieval`. **Only three span verbs; NO read/query
verb at all — no `get_trace`, no `search`.** Adapter pins `langfuse==3.15.0` (OTEL-based) and
**overrides a private hook** (`_parse_langfuse_trace_attributes_from_metadata`) to restore 2.x
`session_id`/`user_id` seams — flagged as needing re-verification on any version bump. Degrades
silently to `None` everywhere.

**Consequence for the ADR: Langfuse is an outbound-only vendor mirror. Our queryable evidence store
is Postgres (`DeepRunLog` + the provenance graph). We cannot build a customer-facing accountability
feature on Langfuse without adding read verbs** — which matters because Langfuse was acquired by
ClickHouse (Jan 2026) and is the obvious "why not just use Langfuse" objection.

### 3.8 Response framework — the remediation rail (thin but real)

- Lifecycle: `PROPOSED --approve--> EXECUTED --rollback--> ROLLED_BACK`; `PROPOSED --reject-->
  REJECTED`; execute-fail → `FAILED`. Terminal = {REJECTED, ROLLED_BACK}.
- Aggregate is a frozen dataclass; every transition returns a NEW entity, guarded by `_guard` →
  `IllegalTransitionError`. ORM adds `kind`, indexes `(workspace, status, -requested_at)` and
  `(workspace, finding_fingerprint)`. Docstring: *"`spec` and `inverse_spec` are written once and
  never change — that immutability is what makes the rollback trustworthy."*
- ⚠ **The "registry" of actions is a 2-value enum, not a plugin registry**: `REVOKE_SG_INGRESS` +
  inverse `AUTHORIZE_SG_INGRESS`. Adding a kind = enum entry + a boto3 branch.
- **Dry-run default TRUE** at three layers (settings `SOC_RESPONSE_DRY_RUN_DEFAULT`, request parsing,
  model default), threading to AWS's native `DryRun`.
- Key sentence for this ADR (`ProposeResponseActionUseCase` docstring): *"Proposing has NO external
  effect … That is why an autonomous agent is allowed to propose (a `reversible_write`) while only a
  human may approve the execution (the `irreversible` step)."*
- `requested_by` is a bare `CharField(64)` — an external agent id fits with no schema change.

### 3.9 Tool risk ladder — the MOST coupled piece

`components/agents/application/policies/tool_risk.py` (SEE-203). Tiers `read < reversible_write <
irreversible`; two orthogonal gates — an **autonomy cap** (`_AUTONOMOUS_ALLOWED = {read,
reversible_write}`; autonomous may NEVER run irreversible even with approval) and **human approval**
for irreversible. `resolve_tool_risk`: explicit `@tool(risk=…)` wins, else registry, else `read`.
Enforcement is `_risk_gated` (`base.py:467–501`), applied in the tool-promotion loop
(`base.py:875–882`); fail-closed on both identity and approval; the tool body never runs on refusal.

- **Coupling: HIGHEST — a Python decorator wrapping a bound method on our `BaseAgent`. It cannot
  observe a tool call it does not wrap.** For a customer's agents, the *tier taxonomy and refusal
  semantics* port cleanly; the *enforcement mechanism* does not — it would have to live at their tool
  boundary or in a proxy/MCP layer we control. This is the single most important negative result in
  the map, and it directly shapes what §5's capture mechanism can and cannot promise.
- **Named gap:** there is **no first-class refusal event type**. A refusal is a *return string*, so it
  survives only as the `tool_output` of a `tool_observation` row. "Provably logged denials" is not
  true today.

### 3.10 The AI service principal (SEE-201)

- `AITeammateProfile` (`infrastructure/persistence/ai/models.py:119–163`): `workspace(OneToOne)`,
  **`user` FK(PROTECT)**, `display_name`, `avatar_url`, `status`, `is_enabled`, `last_run_at`, `config`.
- `AIPermissionGrant` (L166–210): `workspace`, `principal` FK(User), `role="ai_executor"`, `status`,
  `scope_type(workspace|department|project)`, `scope_id`, `actions(JSON)`, `scopes(JSON)`; unique
  `(workspace, principal, role, scope_type, scope_id)`.
- Minting (`actions_service.ensure_teammate`, under `select_for_update`): creates a **real
  `CustomUser`** (`<slug>@<DEFAULT_TEAMMATE_EMAIL_DOMAIN>`, username `<slug>-ai`, random password,
  `is_staff=False`) *"so `Task.created_by` is a real user the team-membership checks accept"*, plus a
  default workspace-scoped `ai_executor` grant with `actions=["*"]`.
- `is_ai_service_principal(user_id, workspace_id)` (`base.py:441–466`) — identity is the profile's
  user, **deliberately independent of any `WorkspaceMembership`** so the write cap holds even if a
  membership is later granted.
- **Asymmetric cap:** writes → `requires_role` refuses with *"Autonomous AI runs cannot perform this
  action directly. Surface it as a finding for a workspace admin to review."*; reads → pseudo-role
  `"ai_service"`, a trusted internal reader that sees every sensitivity tier.
- Kill switch `feature.ai_kill_switch` resolves user → workspace → global, **fail-OPEN by design**
  ("a kill switch that self-engages whenever the flag store hiccups would be its own outage").
- **Coupling: MEDIUM.** The *concept* — an agent is a first-class principal with its own identity
  row, its own grant, and an asymmetric read-everything/write-nothing cap — ports outward perfectly
  and is our strongest conceptual asset. The *implementation* forces every agent principal to be a
  Django `CustomUser` with a synthetic email, which does not fit a customer's agent identity (an
  external ref / OIDC subject / IAM role ARN). **`ProvenanceActor.external_ref` +
  `actor_type="ai_agent"` is the existing escape hatch**; `DeepRun.user` and `Task.created_by` are the
  two hard FKs that would need nullable-plus-external-ref.

### 3.11 The five gaps to name honestly in the ADR

1. **"Provably logged" is currently "conventionally logged"** — no DB-level immutability, no hash
   chain, no signature, no retention policy on `DeepRunLog` or `EntityAuditLog`; both CASCADE away
   with their parent.
2. **No FK from an AI action to the run that produced it** — only a heuristic time+agent match.
3. **Tool-risk refusals have no first-class event type** — denials are return strings.
4. **The sign-off registry has zero registered adapters** — the kernel is real but not wired.
5. **`TracingPort` has no query verb** — Langfuse cannot back a customer-facing feature as-is.

## 4. Findings — Stream B (our ingestion spine) — COMPLETE

### 4.0 ⭐ THE HEADLINE FINDING: the granted-vs-used model already exists

`infrastructure/persistence/provenance/models.py` — the `provenance` context (flag-gated dark behind
`feature.provenance_graph`) **already models exactly the CAN-do vs DID-do gap** this ADR is about:

- **`ProvenanceActor`** — `id, workspace, actor_type, source_system, external_ref, display_name,
  user(FK null), agent_ref(UUID → Agent.agent_id), integration_ref, is_active, first_seen_at,
  last_seen_at`; unique `(workspace, source_system, external_ref)`.
  - **`ActorType` choices already include `ai_agent`** (alongside `human`, `service_account`,
    `vendor_integration`).
  - **`SourceSystem`**: `internal | ai | identity | aws | okta | google_workspace | slack | github`.
- **`ProvenanceResource`** — `resource_type, source_system, external_ref, display_name,
  **asset_urn**` (stamped by a `pre_save` signal bridge via `AssetUrn.canonical` —
  `components/provenance/infrastructure/adapters/django_asset_urn_signal_bridge.py`). So a resource
  is already joined to the asset graph by URN.
- **`AccessGrant`** = **potential** (what the actor CAN do). `PermissionLevel`: read|write|execute|admin.
- **`ProvenanceEvent`** = **actual** (what the actor DID).

Today these rows are populated **from OUR agents** by
`components/provenance/infrastructure/services/ai_backfill_service.py` (reading our `Agent`/`DeepRun`
rows). ADR 0009 D5 wants the graph un-darkened as access-review evidence.

**Consequence for this ADR (decisive):** the data model question — "what is an agent, a tool grant, an
agent action, an identity in OUR SSOT terms" — has a pre-existing, ADR-0004-compliant answer. It is
NOT a new bounded context:

| ADR concept | Existing home |
|---|---|
| an **agent** | `ProvenanceActor(actor_type=ai_agent)` |
| an **identity** | `ProvenanceActor` (+ `user` FK for on-behalf-of; `source_system` for the IdP) |
| a **tool grant** (CAN) | `AccessGrant(actor, resource, permission_level)` |
| an **agent action** (DID) | `ProvenanceEvent(actor, resource, …)` |
| the **resource** it touched | `ProvenanceResource.asset_urn` → joins the asset graph by value |
| the **exposure statement** | `Finding` (source = new slug), `attributes` JSON bag |

The gap is not the schema. The gap is (a) a **capture path** that fills these rows from a
*customer's* estate rather than our own, and (b) the **detectors** that turn grant-vs-event deltas
into findings. That is a much shorter path than building AI-SPM from scratch — **thesis confirmed on
the storage side**; the capture side is where the real work is (§5).

### 4.1 Finding SSOT — `infrastructure/persistence/findings/models.py`

`Finding` fields: `id(UUID PK)`, `workspace(FK)`, **`source(Char64)`** — the pillar slug and the de
facto kind discriminator, **`fingerprint(Char255)`**, **`asset_urn(Char512)`**, `severity(Char16)`,
`status(Char16, default open)`, `title(Char512)`, `description`, `remediation`, `compliance(JSON)`,
**`attributes(JSON)` — the pillar-specific extension bag**, `scan_run_id(Char64, blank for run-less
sources)`, `status_reason`, `suppress_expires_at`, `first_seen_at`, `last_seen_at`, `resolved_at`.

- Identity: `UniqueConstraint(workspace, source, fingerprint)`.
- **`source` is a free CharField — there is NO enum and NO migration needed for a new kind.**
- Live values: `cloud_posture.prowler`, `cloud_posture.prowler.vercel`, `container_security.trivy`,
  `code_security.opengrep`, `code_security.planted_instructions`, `cloud_graph.attack_path`,
  `logwatch.error`, `logwatch.optimization`.
- `FindingRisk` (ADR 0013) carries `score/band/factors/epss/in_kev/exposure/exposure_unknown`.
- Write path is ONE use case: `record_observed_finding_use_case.py` (create → `FindingRaised(is_new=True)`;
  unchanged re-observation bumps `last_seen_at` and **emits nothing** — steady-state noise suppression).
- Scanners emit `FindingObserved` and **never write a Finding row** (owner-persists).

### 4.2 AssetUrn — `components/shared_kernel/domain/security.py`

`AssetUrn.canonical(source_system, external_ref)` → passes through anything already `arn:`/`urn:`,
else `urn:<source_system.lower()>:<external_ref>`. `.provider` parses it back. Existing namespaces:
`arn:aws:…`, `urn:vcs:github:<owner>/<repo>`, `urn:vercel:<ref>`. **A new namespace costs zero schema
change** — the discipline is that it must be *decided*, never defaulted (ADR 0021 D1's "succeed and
lie" trap).

Graph nodes are `CloudAsset` (`provider`, `arn` = dedup key, `asset_urn`, `resource_type` free
CharField, `exposure` public|internal|private, `attributes`, `is_sample`) + `CloudAssetEdge`
(`relation`: can_assume|attached_to|allows_ingress_from|has_policy) + materialized `AttackPath`.
Findings attach to assets **purely by URN value — nothing joins by FK.**

### 4.3 ScannerPort + registry

`components/shared_kernel/application/ports/scanner_port.py` — one method
`scan(target, *, on_progress) -> ScanResult`; dataclasses `ScanTarget(identifier, credentials, params)`,
`ScanArtifact`, `ScanResult(findings, engine, engine_version, counts, artifacts)`.
Registry `components/scanning/application/providers/scanner_registry.py`:
`RegisteredScanner(factory, queue, post_ingest_factory, credentials_factory, failure_factory)`.

**New-pillar copy template (proven 4×):** adapter + normalizer + `application/providers/scanner_provider.py`
+ one `_REGISTRY` line + one `_SOURCE_BOARD` entry. **No new Celery task, no new pipeline** —
`components/scanning/infrastructure/tasks/scan_tasks.py::dispatch_scan/run_scan` is generic, and
`run_scan_service.run_scan_and_ingest` records the `ScanRun` then emits one `FindingObserved` per
finding + one `ScanCompleted` after commit.

### 4.4 LogSourcePort (ADR 0008)

`components/integrations/application/ports/log_source_port.py` — **integrations-internal, NOT shared
kernel**. Two methods: `verify(config) -> LogSourceHealth`, `read_window(config, *, since, limit) ->
LogWindow(records, cursor, objects_scanned)`.

Adapters: `s3_log_source_adapter.py` (`KIND="s3"`, always on) and `cloudwatch_log_source_adapter.py`
(`KIND="cloudwatch"`, behind `feature.log_source_cloudwatch`). Datadog/Splunk/Webhook are **model
choices only — no adapters exist.** Registry `log_source_provider.py` fails CLOSED on the flag check.

`WorkspaceLogSource`: `workspace, kind, name, config(JSON, opaque per kind), secret_ref(envelope id,
never plaintext), status, cursor(Char1024), last_verified_at, last_error`.
Iteration: `components/integrations/application/log_ingest_service.py::read_source_windows(...)`,
`scan_connection(...)`, `scan_workspace_for_errors(...)`; `LogRecord(service, level, message, raw, ts,
source_kind, source_id)`.

**Hard rule in that module's docstring: never run an LLM over the raw log firehose.** Deterministic
first pass; only a CONFIRMED detection reaches the LLM. This binds any log-derived agent detection.

### 4.5 Consent precedents (all fail-closed)

- **`VcsConnection.repo_allowlist`** (JSON list of `owner/repo`) enforced at **five** layers:
  `vcs_scan_access_provider.py` (`resolve_scan_connection` trigger-time, `vend_repo_read_access`
  scan-time re-check, `list_scannable_repos`, `read_repo_file` pinned to the scanned SHA),
  `open_draft_pr_use_case._require_allowlisted_repo`, `check_pull_request_merged_use_case`,
  `vcs_connection_service.verify` (probes EVERY allowlisted repo), and input validation in
  `components/code_security/domain/repo_reference.py` (strict regex, no `..`, no shell metachars).
  `None` from the vend ⇒ the scan **fails loud** rather than running consentless.
- **AWS**: `AwsOrganizationConnection.external_id` is **vendor-generated**
  (`aws_connection_service.py:74` → `f"autosec-{secrets.token_urlsafe(24)}"`), never customer-chosen;
  the onboarding template attaches managed read-only `SecurityAudit` + an inline read-only policy,
  with the trust policy conditioned on `sts:ExternalId` (confused-deputy defense).
- **Vercel**: `VercelConnection` — named team is the consent boundary; Viewer-role, single-team,
  expiring token.

### 4.6 The output loop — where a new finding kind plugs in

1. Emit `FindingObserved` with a new `source`.
2. Add `_SOURCE_BOARD[source]` in
   `components/agents/application/handlers/finding_raised_board_handler.py` →
   `{source_type, detector_key, flag, min_severity, default_agent_type, build: <card builder>}`.
   **Unmapped sources silently no-op** — the classic miss.
3. Add the board `source_type` to `ROUTABLE_SOURCE_TYPES` in
   `components/shared_kernel/domain/triage.py` (and `PR_REMEDIABLE_SOURCE_TYPES` if PR-remediable).
   Its docstring: *"Growing this is the ENTIRE routing change needed for a new finding kind (plus the
   specialist's triage tool — routable without a tool is a silent no-op)."*
4. Give the specialist a triage tool.

`TriageState`: `QUEUED, DRAFTING, FIX_READY, FIX_UNVERIFIED, NO_FIX, NOT_ROUTED`.
`remediation_target(source_type, payload)` → `TARGET_REPO|TARGET_IMAGE|TARGET_CLOUD|TARGET_SERVICE|
TARGET_NONE`; **only `repo` gets the draft-PR affordance** — directly relevant to "what does
remediation mean for an over-permissioned agent" (§6 of the ADR).
Draft PR is ONE engine (`open_draft_pr_use_case.py`, ADR 0017 D0: a new source adds a patch
**strategy**, never a second engine), with 5 ordered gates and a throttle.

### 4.7 Detector registry

`components/agents/infrastructure/adapters/actions/detectors/registry.py` — `@registry.register` on a
`BaseDetector` subclass with a unique `slug`. Domain contract in
`components/agents/domain/detectors/base.py`: `should_run(ctx)`, `gather_signals(ctx)`,
`execute(ctx) -> Iterable[DetectorResult]`; `DetectorContext` carries `invoke_agent` (the
LLM-after-detection hook). Existing: logwatch, cloud_graph_sync, cloud_graph_attack_paths,
posture_report, projects, provenance, run_quality, finding_observed_bridge.

`finding_observed_bridge.py` carries `LOGWATCH_SSOT_SOURCES` — *"Adding a slug here is how another
detector-based pillar joins the SSOT."* **This is the seam a detector-based (non-scanner) agent
accountability pillar would use.**

### 4.8 Does anything already model a CUSTOMER's AI estate? — No.

Verified by broad grep (`ai_asset`, `llm*`, `model_endpoint`, `ai_system`, `agent_inventory`,
`shadow_ai`, `bedrock`, `sagemaker`, `mcp_server`, `aibom`, …). Every hit is one of:

1. **Our own AI runtime** — `infrastructure/persistence/ai/agents/models.py`.
2. **Our own AI-SPM narration** — `components/agents/application/services/ai_governance_service.py`
   (docstring says it covers OUR fleet) + `ai_governance_agent.py`.
3. **Two thin edges that DO touch customer AI risk and are ALREADY on the spine:**
   - `components/code_security/planted_instruction_reporter_service.py` —
     `SOURCE = "code_security.planted_instructions"`, a prompt-injection heuristic over **the
     customer's own repo content**, emitted as a real `FindingObserved` with
     `urn:vcs:github:<repo>`, board `source_type` `ai.planted_instructions`. **This is the closest
     existing precedent for "an AI-shaped finding about the customer" — and proof the pattern works.**
   - `components/knowledge/domain/value_objects/injection_scan.py` (the reused OWASP-LLM01 heuristic).

Net-new pieces required: a customer-AI-system/endpoint connection model (copy `WorkspaceLogSource`'s
kind+config+cursor+secret_ref shape and `VercelConnection`'s named-scope consent shape), an
`ai_*_allowlist` consent boundary (copy `repo_allowlist` enforcement), a decided URN namespace, and
new `Finding.source` values. **No Finding-table migration.**

## 5. Findings — Stream C (the capture problem)

_pending_

## 6. Findings — Streams D–H

_pending_

## 7. Open questions / could-not-verify

_pending_
