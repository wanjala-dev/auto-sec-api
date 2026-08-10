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

## 5. Findings — Stream C (the capture problem) — COMPLETE

### 5.0 ⭐ The single most important sentence in the whole research pass

> **Identity is absent by construction from the AI-observability stack.** Verified across the OTel
> registry, the GenAI agent-spans doc, and the genai repo's own attribute registry: **there is no
> principal / subject / credential / authorization attribute anywhere in `gen_ai.*`.** The only
> verified identity in any of the five mechanisms is MCP's OAuth token `sub` — and MCP Authorization
> is optional and covers only MCP-routed tools.
> **Every accountability claim a security product makes here is a JOIN it performs, not a field it
> reads.** That join — behaviour telemetry × credential provenance — is the defensible product surface.

This is the moat sentence for this ADR, and it is a research result, not an assertion.

### 5.1 OpenTelemetry GenAI semantic conventions — useful schema, unstable footing

- **Moved out of the main semconv repo during 2026.** Main repo **v1.42.0 (2026-06-12)** deprecated
  and moved all `gen_ai.*`; **v1.43.0 (2026-07-03)** ships none of it. New home:
  https://github.com/open-telemetry/semantic-conventions-genai
  (https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/,
  https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- **Nothing is Stable.** As of 2026-07-17 no GenAI span/event/metric/attribute is marked Stable, and
  ⚠ **the new repo has NO releases or tags** (verified:
  https://github.com/open-telemetry/semantic-conventions-genai/releases → "There aren't any releases
  here"). **Pinning means pinning a commit on `main`** — a real problem under `pin-versions.md`.
- `gen_ai.operation.name` ∈ `chat, create_agent, embeddings, execute_tool, generate_content,
  invoke_agent, invoke_workflow, retrieval, text_completion`.
- **Agent spans:** `create_agent {name}`, `invoke_agent {name}`; attributes `gen_ai.agent.id`,
  `.name`, `.description`, `.version`, `gen_ai.conversation.id`, plus request/response/usage.
  Content (`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
  `gen_ai.tool.definitions`) is **Opt-In (off by default)**.
- **Tool spans:** name `execute_tool {tool}`, kind INTERNAL. Required `gen_ai.operation.name`,
  `gen_ai.tool.name`; recommended `gen_ai.tool.call.id`; **Opt-In** `gen_ai.tool.call.arguments`,
  `gen_ai.tool.call.result`. `gen_ai.tool.type` ∈ `function | extension | datastore` only.
- Native emitters: **Vercel AI SDK 7** (best), Mastra (pins semconv v1.38.0 — interop wrinkle),
  Pydantic AI, Strands. **OpenAI Agents SDK does NOT emit OTel GenAI natively** (own tracing;
  bridge via `openinference-instrumentation-openai-agents`).
- ⚠ **OpenInference (Arize) is a COMPETING convention, not the OTel one** — ingesting both requires a
  normalization layer. Budget for it. (https://arize-ai.github.io/openinference/spec/)

### 5.2 Vercel AI Gateway — good identity axis, blind to tools

- Code change is a **base-URL swap** (`https://ai-gateway.vercel.sh/v1`) or, with the AI SDK, just a
  plain model string (`model: 'openai/gpt-5.6-sol'`) — **Isaac may already be on it**. OIDC tokens
  work instead of an API key when running on Vercel.
  (https://vercel.com/docs/ai-gateway/getting-started/text)
- **Logs per request:** time, status, model, provider, tokens (input/output/cache-read/reasoning),
  cost, duration, region; detail adds generation ID, **the originating API key or project**, TTFT,
  ZDR flag, and a **Fallback Path**. **No prompt/completion bodies. No tool calls.**
  (https://vercel.com/docs/ai-gateway/observability-and-spend/logs)
- ⭐ **`ai-reporting-user` and `ai-reporting-tags` HTTP headers** — documented explicitly for a
  "platform or proxy layer [that] stamps context onto traffic **without modifying application
  code**"; up to 10 tags, `user` ≤256 chars; become queryable `group_by` dimensions.
  **This is the cheapest per-agent identity axis that exists.**
  (https://vercel.com/docs/ai-gateway/observability-and-spend/custom-reporting)
- **Custom Reporting API**: `GET https://ai-gateway.vercel.sh/v1/report`, Bearer auth, `group_by` ∈
  {day, user, model, tag, provider, credential_type, zero_data_retention, api_key_name}. **Pro/Ent
  only, beta, returns AGGREGATES not per-request rows**, priced at $0.075/1k tag-or-user-ID writes
  and $5/1k queries. `gateway.getGenerationInfo({id})` fetches one generation.
- **Retention 30 days** for request details (date picker allows 36 → a documented 6-day gap).
- **Structurally cannot see:** tool execution, direct-to-Stripe calls, MCP tool calls, or any agent
  that bypasses the gateway. **You cannot prove coverage completeness from inside a gateway.**

### 5.3 ⭐⭐ Vercel Tracing — outbound fetch spans with ZERO code change

Verified verbatim at https://vercel.com/docs/tracing (updated 2026-07-06):

> "Vercel automatically instruments your application **without needing any additional code
> changes**. When you have set up Trace Drains or enabled Session Tracing … you'll be able to
> visualize traces for: **Vercel infrastructure** … **Outbound HTTP calls**: The HTTP requests made
> from your function will be displayed as **fetch spans**, displaying information on the length of
> time, location, and other attributes."

- **Trace Drains** (https://vercel.com/docs/drains/reference/traces): **OTLP/HTTP exclusively**
  (no gRPC; port 4318 `/v1/traces`), JSON or Protobuf, to **any custom endpoint**. Vercel stamps
  `vercel.projectId` / `vercel.deploymentId`. **Per-drain sampling rules** by environment,
  percentage, path prefix. **Pro/Enterprise, $0.50/GB.**
- ⭐ **Provisionable via the Drains REST API** (`POST` with `schemas: {trace: {version: "v1"}}` —
  https://vercel.com/docs/rest-api/drains/create-a-new-drain) — **so we can create the drain
  ourselves rather than walking the customer through a UI.**
- Limits: 10 MB compressed per request; spans >1 MB dropped after attribute truncation (marker
  `<attr>.truncated: true`); **custom spans from Edge-runtime functions do NOT appear** in Session
  Tracing or Trace Drains.
- `@vercel/otel` (`registerOTel({serviceName})` in `instrumentation.ts`) is a separate ADDITIVE layer
  for framework/custom spans — **not required** for infra + fetch spans.
- ⚠ **[UNVERIFIED]** whether fetch spans ever carry request/response bodies. Standard OTel fetch
  instrumentation does not. **Do not claim fetch spans reveal what was sent to Stripe** — they reveal
  *that* Stripe was called, when, and with what status.

### 5.4 ⚠ How this squares with ADR 0021 D5 (must be stated precisely)

ADR 0021 D5 refused **Log Drains**. Trace Drains are a **different product with a different data
shape**, so this is not a silent re-opening — but the distinction must be made explicitly:

| D5's reason to refuse Log Drains | Does it bind Trace Drains? |
|---|---|
| No `logs` integration scope exists (runtime logs 403 even with every scope) | **No** — Trace Drains are provisioned through the Drains REST API, a different surface. |
| Pro/Enterprise-gated at **$0.50/GB on the customer's bill** | **YES — binds identically.** Trace Drains are also Pro/Ent at $0.50/GB. Inherit this constraint; mitigate with the per-drain sampling rules. |
| Drain payloads are **attacker-authored strings** (`proxy.path`, `userAgent`, `message`) entering the AI pipeline | **Materially weaker.** Fetch spans are **platform-generated** (host, method, status, duration), not attacker-authored free text. ⚠ But this protection **evaporates the moment AI SDK content attributes are enabled** — `gen_ai.input.messages` IS attacker-influenced text. Hence the metadata-only default in D3. |

### 5.5 ⭐ Vercel AI SDK 7 — the richest signal, one line, once

From https://ai-sdk.dev/docs/ai-sdk-core/telemetry (documented for **AI SDK 7.x, Latest**):

```ts
import { registerTelemetry } from 'ai';
import { OpenTelemetry } from '@ai-sdk/otel';
registerTelemetry(new OpenTelemetry());   // once, at startup
```

> *"Once a telemetry integration is registered, all AI SDK calls emit telemetry events by default."*

Per-call config exists only to **opt out** (`telemetry: {isEnabled: false}`) or attach a `functionId`.

- Emits native GenAI-semconv spans: `invoke_agent {modelId}` (root), `chat {modelId}` (per step),
  **`execute_tool {toolName}`** (per tool call), `embeddings`, `rerank`.
- Tool span attributes: `gen_ai.tool.name`, `.call.id`, `.type`, **`.call.arguments`**,
  **`.call.result`**, `gen_ai.execute_tool.duration`.
- ⚠⚠ **"By default, both inputs and outputs are recorded"** — the **OPPOSITE** of the OTel spec's
  Opt-In posture. Disable via `recordInputs` / `recordOutputs: false`. **For a customer handling card
  data this is a privacy hazard that must be called out and defaulted off.**
- ⚠ **The version split is the single biggest friction variable.** AI SDK **v6 and earlier** used
  per-call `experimental_telemetry: {isEnabled: true}` — i.e. **one edit per call site across 60
  agents** instead of one edit total. Confirmed by Langfuse's integration doc, which documents both
  (v7 `registerTelemetry(...)`, Node 22+; v6 `experimental_telemetry`).
  (https://langfuse.com/integrations/frameworks/vercel-ai-sdk)
- ⚠ Doc inconsistency **[UNVERIFIED]**: Vercel's AI Gateway page (2026-07-28) says it "works with AI
  SDK v5 and v6" while ai-sdk.dev documents 7.x as Latest.

**⭐ The key architectural insight: AI SDK 7 telemetry + a Vercel Trace Drain = agent/tool spans
delivered to an arbitrary OTLP endpoint, with one line of app code and one dashboard/API config —
and the tool layer (which a gateway cannot see) and the egress layer (which the SDK cannot see)
arrive in ONE correlated trace, because both ride the same `traceId`.**

### 5.6 MCP server-side capture — the only verified identity, but no audit trail

- Current revision **`2026-07-28`** (https://modelcontextprotocol.io/specification/versioning).
  It is a big revision: **stateless architecture** (`initialize` handshake and `Mcp-Session-Id`
  removed), **W3C Trace Context formalized in `_meta`**, six authorization-hardening SEPs, JSON
  Schema 2020-12, and **Logging / Roots / Sampling all DEPRECATED**.
- **MCP `logging` is server→client and is now deprecated** (SEP-2577: "New implementations SHOULD NOT
  adopt it… migrate to `stderr` … **or to OpenTelemetry for structured observability**"). It also
  explicitly **forbids** the content an audit trail needs: log messages *"MUST NOT contain:
  Credentials or secrets, Personal identifying information, Internal system details…"*
- **There is NO audit event schema, no standard for recording tool-call arguments/results
  server-side, no cross-server correlation ID, no retention or tamper-evidence model.** A server
  operator builds all of it.
- Two open, **unmerged, unsponsored** SEPs confirm the gap: **SEP-2817** "AI Invocation Audit Context
  in Request `_meta`" (Draft, seeking sponsor; carries **client-asserted** `invocationReason`,
  `model`, `userIntent`, `turnId` and says outright these are **"not authorization evidence"**), and
  **SEP-3004** "Tamper-Evident Audit Record Contract" (no sponsor) **[UNVERIFIED in detail]**.
- ⭐ **Authorization is the one real identity primitive**: an MCP server acts as an **OAuth 2.1
  resource server**; RFC 9728 Protected Resource Metadata (servers MUST), RFC 8707 Resource
  Indicators (clients MUST send `resource`), RFC 9207. *"MCP servers MUST validate that access tokens
  presented to them were specifically issued for their use."* A compliant server can log `sub`/`aud`/
  `scope`. **Authorization is OPTIONAL overall** and SHOULD NOT be used over stdio.
- Confused-deputy rules: *"The MCP server MUST NOT pass through the token it received."* Spec warns
  tokens "cached or **logged on the server**" are a theft vector → **log derived claims, never the
  raw bearer.**
- `_meta.io.modelcontextprotocol/clientInfo` is **self-reported and explicitly NOT verified** —
  *"Implementations SHOULD NOT … rely on them for security decisions."*
- **Enterprise-Managed Authorization** (SEP-990) is the closest standardized delegation story — an
  **ID-JAG** carrying a `sub` claim — but is an **opt-in extension, not core**. **SEP-1028**
  "Delegated Authorization" (on-behalf-of) is still **Proposal, unmerged**.
- ⚠ Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) exist,
  but the spec is blunt: *"clients MUST consider tool annotations to be untrusted unless they come
  from trusted servers."* **You cannot ground a risk classification on declared hints** — classify by
  observed behaviour or pin known-good servers.
- `mcp.*` semconv also moved to the genai repo, Development-stage, captures `mcp.method.name`,
  `mcp.protocol.version`, `mcp.resource.uri`, `mcp.session.id` — **no tool arguments, no caller
  identity.**

### 5.7 Log-based reconstruction elsewhere (for contrast)

- **Vercel Log Drains carry NO outbound-call field at all** — every field describes the **inbound**
  request (`proxy.method/host/path/userAgent/clientIp/wafAction/...`).
  (https://vercel.com/docs/drains/reference/logs)
- ⚠ **Retention is brutal and the window may already be closed:** Vercel runtime logs retain
  **Hobby 1 hour · Pro 1 day · Enterprise 3 days · +Observability Plus 30 days** (viewable in any
  14-consecutive-day window; $1.20 per 1M events; on by default only for paid Pro teams created or
  upgraded **on or after 2026-04-03**). (https://vercel.com/docs/logs/runtime,
  https://vercel.com/docs/observability/observability-plus)
- **AWS (not Isaac's stack, but the contrast matters):** Bedrock `InvokeModel`/`Converse` are
  CloudTrail **management** events (free, default); `InvokeAgent`/`Retrieve`/`InvokeFlow` are **data
  events requiring advanced selectors at extra cost**. CloudTrail proves **which IAM role** called
  Bedrock — never which of 60 in-app agents unless each assumes a distinct role. **Bedrock Model
  Invocation Logging** has an optional caller-supplied **`requestMetadata`** bag that CAN say
  "agent #37" — **and it requires a code change**. VPC Flow Logs are L3/L4 only and useless against
  shared CDN IPs.
- **Stripe:** Workbench Logs record every API request, filterable by date/status/method/endpoint/
  resource ID/source. The native attribution primitive is **Restricted API Keys (`rk_…`), which
  Stripe recommends creating one per part of your integration** — named, scoped, independently
  revocable. **One RAK per agent is the correct answer, and it is a provisioning decision, not a
  logging one.** ⚠ **[UNVERIFIED]**: request-log retention, whether a "Key name" column is exposed,
  and `X-Stripe-Client-User-Agent` as a caller-tagging mechanism (**do not cite**).

### 5.8 Ranking by deployment friction FOR ISAAC

| # | Mechanism | Code change | Once or per-agent? | Signal |
|---|---|---|---|---|
| **1** | **Vercel Trace Drains** | **NONE** | **Once** (provisionable by API) | Infra spans + **outbound fetch spans** for every function — sees egress to both the LLM provider and Stripe. No content, no tool semantics, **no identity**. Pro/Ent, $0.50/GB. |
| **2** | **AI SDK 7 `registerTelemetry()`** | **One line, once** | Once per app (**per call site on v6**) | **Richest available**: `invoke_agent`/`chat`/**`execute_tool`** with tool name, call id, arguments, results, tokens. Rides the same drain. Inputs/outputs on by default — card-data hazard. |
| **3** | **Vercel AI Gateway** | Base-URL/model-string swap (may already be on it) | Per client construction site | Model/provider/tokens/cost/status/routing + **originating API key**; **`ai-reporting-*` headers give a per-agent identity axis with no app-code change**. No content, **no tool calls**, blind to direct-to-Stripe. |
| **4** | **OTel GenAI semconv** | — | — | **A schema, not a mechanism.** Free if AI SDK 7 emits it. Unversioned-`main` pinning risk; OpenInference normalization tax. **Zero identity attributes.** |
| **5** | **MCP server-side** | Server implementation work | Per MCP server, MCP-routed tools only | **The only verified caller identity (OAuth `sub`)** — but the spec gives no audit trail; you build all of it. Invisible to Isaac's direct Stripe calls. Not deployable against 60 existing agents. |

### 5.9 Three cross-cutting facts to carry into the ADR verbatim

1. **Identity is absent by construction** (§5.0) — every accountability claim is a **join**, not a
   field read.
2. **The tool-execution blind spot is where the risk lives.** Gateways see the LLM hop. The agent's
   `charge_card` tool calling `api.stripe.com` traverses **no gateway**. Only two things see it: the
   framework's `execute_tool` span and Vercel's platform fetch spans. **Any architecture relying on
   gateway logs alone is blind precisely where money moves.**
3. **Retroactive reconstruction is largely impossible and the window may already be closed.** Frame
   the product as **"turn on accountability going forward,"** never as forensic recovery.

## 6. Findings — Stream D (identity / permission surface / tamper-evidence) — COMPLETE

### 6.1 What a shared API key structurally destroys (primary source)

Google Cloud IAM best practices, verbatim:

> "Cloud Audit Logs creates a log when a service account modifies a resource, but **if the service
> account is authenticated with a service account key, there is no reliable way to tell who used the
> key.**" … "if multiple applications share a service account, you might not be able to trace
> activity back to the correct application."
> — https://docs.cloud.google.com/iam/docs/best-practices-service-accounts

Note the contrast Google draws: **impersonation preserves accountability where key-based auth
destroys it** — "authenticating … by impersonating the service account with user credentials logs
the principal who acted as the service account." **The credential type determines whether
attribution is even possible.**

Three losses, in ADR language:
1. **Attribution** — the identifier in the log is the key, not the agent. **No downstream correlation
   recovers it, because the information was never transmitted.** Anything else is inference, not
   evidence, and will not survive a dispute.
2. **Selective revocation** — you cannot revoke agent 7 of 60 without revoking all 60.
3. **Differential scoping** — the grant is the union of what all 60 agents need; **every agent holds
   the maximum privilege of the noisiest one.** For a shared-key fleet the granted-vs-used gap is not
   sloppiness, it is arithmetic.

### 6.2 Entra Agent ID — **GA (April 2026)**, and it independently validates our D1 data model

- GA per https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id (`ms.date: 2026-05-01`).
  Conditional Access for Agents + ID Protection for Agents GA rolled out **early July → early August
  2026** (MC1395007). Some sub-features (admin-center blueprint wizard) remain **Preview**.
- **Object model:** *agent identity blueprint* (holds the credentials — like an app registration) →
  *agent identity* (the running instance; **has NO credentials of its own**, authenticates via
  blueprint-issued tokens) → *blueprint principal* (tenant-local, "enables it to acquire tokens and
  appear in audit logs") → optional *agent's user account* (1:1, for systems needing a user object).
  **N instances, one credential, N distinct identities in the token and the log.**
- **Two patterns:** interactive agents use **delegated permissions + OBO**; autonomous agents use
  **client credentials** with their own identity.
- **Governance:** Owners (technical) / **Sponsors (business accountability, no technical access)** /
  Managers, plus lifecycle workflows that "automatically transfer sponsorship when a sponsor changes
  roles or leaves, to prevent orphaned agents."
- ⭐ **Audit design — the part to copy.** Microsoft did NOT build a new log; they **extended the
  existing audit schema**: a new `agentType` property on `auditAppIdentity`, `auditUserIdentity`,
  `targetResource`; a new `auditActivityPerformer` type; a new **`blueprintId`** to correlate
  instance → blueprint; and a new `agentSignIn` sign-in event type, filterable in Graph beta.
  (https://learn.microsoft.com/en-us/entra/agent-id/sign-in-audit-logs-agents)
  > **"Agent-ness is a property stamped onto the existing actor fields, not a parallel log."**
  This independently validates ADR D1: extend `ProvenanceActor`/`ProvenanceEvent`, do **not** build a
  parallel agent-events table.
- **Caveat:** attributes actions to **Entra-protected resources**. Tells you nothing about Stripe.

### 6.3 RFC 8693 — the cleanest conceptual frame, and its honest limit

https://www.rfc-editor.org/rfc/rfc8693.html

> **Impersonation:** "when principal A impersonates principal B, then insofar as any entity receiving
> such a token is concerned, they are actually dealing with B."
> **Delegation:** "principal A still has its own identity separate from B, and it is explicitly
> understood that while B may have delegated some of its rights to A, any actions taken are being
> taken by A representing B."

**Impersonation is the accountability-destroying pattern** — name it as the anti-pattern. The `act`
claim carries the chain (outermost = current actor, nested = prior); `may_act` pre-authorizes.

⚠ **The limit the ADR must not gloss:**
> "For the purpose of applying access control policy, the consumer of a token MUST only consider the
> token's top-level claims and the party identified as the current actor by the `act` claim. **Prior
> actors identified by any nested `act` claims are informational only.**"

So token exchange proves the **immediate** delegation hop authoritatively; the deeper chain is
informational. **Do not claim "cryptographically provable delegation chain."** For a multi-hop agent
chain you get an auditable record, not an enforceable one — and that gap is itself sellable.

Newer IETF work: **`draft-ietf-oauth-identity-chaining-17` (2026-07-19, expires 2027-01-20)**,
Standards Track WG doc — a **profile** of RFC 7523 + RFC 8693, never mentions agents.
**Identity Assertion Authorization Grant** — `draft-parecki-…-05` expired, **replaced by
`draft-ietf-oauth-identity-assertion-authz-grant`** (WG adoption = maturity signal). Keycloak 26.5
shipped JWT authorization grant + identity chaining (Jan 2026).
**AIP / Invocation-Bound Capability Tokens** (arXiv 2603.24775, 2026-03-27 + `draft-prakash-aip-00`)
— ⚠ individual submission + preprint, **cite as directional only**; its "~2,000 MCP servers scanned,
all lacked authentication" figure is uncorroborated.

### 6.4 Okta / Auth0

- **Okta for AI Agents** — vendor-stated **GA 2026-04-30**; framed as *"where are my agents, what can
  they connect to, and what can they do?"*; agent discovery incl. **shadow agents**, credential vault
  with rotation, and a **kill switch**. ⚠ the press-release fetch returned a garbled announcement
  date — treat announcement date as unverified.
- **Identity Security Fabric** (Oktane 2025) — ISPM discovers AI agents and risks around service
  accounts/API keys/OAuth tokens; Universal Directory attributes **risk classification and ownership
  to every non-human identity**.
- **Cross App Access (XAA)** — the substantive standards contribution, built on the Identity
  Assertion Authorization Grant. Okta Workforce access via OIN **from August 2026**; Auth0 B2B early
  access **end of July 2026**. ⭐ **Anthropic's beta program includes Okta as featured IdP** for
  governing Claude's access to participating MCP providers — the clearest signal XAA is the emerging
  MCP authorization path.
- **Auth0 for AI Agents — GA 2025-11-19.** Token Vault (35+ apps, agent never holds credentials);
  ⭐ **Asynchronous Authorization (CIBA)** — human-in-the-loop approval for critical actions with rich
  authorization data shown to the approver — *the single most directly relevant primitive to "an agent
  holds write access to Stripe"*, and the external analogue of our `sign_off` kernel; FGA for RAG.
  ⚠ **Honest finding: the GA announcement does not describe individual agent identities, attribution,
  or audit trails.** Auth0 is strong on delegated access + approval, **weaker on attribution** than Entra.

### 6.5 SPIFFE/SPIRE — solves workload identity, not on-behalf-of

> SPIFFE can say "this workload is X," but it cannot say "this workload is X, **acting on behalf of
> user Y**, with a limited scope, for a bounded time, and here is the audit record."

IETF **WIMSE** is addressing it; emerging consensus is layered — **SPIFFE underneath for machine
identity, OAuth/OBO on top for the on-behalf-of assertion**. For a 60-agent Vercel/TypeScript
startup, **SPIFFE is not the answer** (SPIRE server + per-workload attestors is real cost).

### 6.6 ⭐ Can you attribute to a specific agent AND the human? — For Isaac, in practice: no.

Five conditions must ALL hold: (1) per-agent identity, (2) **delegation not impersonation**,
(3) the resource server **records both subject and actor** — *"this is where most integrations fail:
the token carries the information and the log discards it"*, (4) no static long-lived secret, (5)
retained + tamper-evident logs.

Entra satisfies 1–3 for Entra-protected resources. **Nothing satisfies this across a third-party SaaS
API like Stripe without the customer building it.** For Isaac — Vercel functions are stateless and
ephemeral so the natural credential is a shared env var; Node/TS agent frameworks default to one API
key per integration per process, not per agent.

> **The wedge, stated honestly: the market has built the standards for agent attribution and the
> IdP-side implementations, but the delegation chain terminates at the edge of the SaaS APIs where
> the money actually moves — provided we are honest that for shared-key customers we are
> RECONSTRUCTING, not PROVING.**

⚠ The circulating stats (97% of NHIs overprivileged; 80% of agents act beyond scope; 18% of MCP
deployments scope tool permissions) trace to vendor blogs with **no cited methodology — do not use
them as facts.**

### 6.7 Enumerating the capability surface — what is programmatically discoverable

| Surface | How | Programmatic? |
|---|---|---|
| **MCP tools** | `tools/list` | **Yes — fully, at runtime** |
| In-code tool definitions | AST/grep, framework-specific | Partially |
| OAuth scopes granted | IdP admin API, token introspection | Yes |
| Cloud IAM roles assumable | IAM policy APIs, assume-role trust policies | Yes |
| API keys in env | env scan / secrets-manager inventory | Presence yes; **key→capability needs the provider API** |
| **Effective permission of an API key** | provider-specific; **Stripe = Dashboard only** | **Largely no** |

⭐ **MCP is the best-instrumented surface.** `tools/list` is paginated and first-class; a tool carries
`name/title/description/inputSchema/outputSchema/annotations`. Servers declare
`capabilities.tools.listChanged` and **SHOULD emit `notifications/tools/list_changed`** →
**capability-surface drift is detectable in real time.** *"Agent X gained a new write tool at 14:02
Tuesday" is a finding* (this is ADR detector F4). ⚠ But annotations are **untrusted** per spec — never
score risk on declared hints. Also: the MCP spec's own security guidance already says clients should
*"Log tool usage for audit purposes"* — we are aligned with the protocol's intent, not fighting it.

### 6.8 ⭐⭐ Stripe — the vendor already recommends our recommendation, and already ships manual CIEM

https://docs.stripe.com/keys/restricted-api-keys

- RAKs (`rk_live_`/`rk_test_`) assign **per-resource None / Read / Write**; all Stripe APIs support them.
- > *"Stripe recommends always using RAKs instead of unrestricted secret keys, **especially when
  > giving a key to an AI agent.** Use RAK permissions to limit what an agent can do in your account."*
- > *"**Use one restricted key per service or use case.**"* → maps 1:1 onto one key per agent.
  **Our core provisioning recommendation is the vendor's own guidance, not our invention.**
- ⭐ **Stripe already documents the granted-vs-used loop, done by hand:** create key with broad
  permissions → run it → *"View request logs to see all of the requests made with that key"* →
  map `GET`→read, `POST`/`DELETE`→write → *"remove any permissions your key did not use."*
  **That is CIEM, manually, for Stripe. Automating exactly this for agents is the product.**
- **Attribution:** request logs are **per-key**. So per-agent Stripe attribution works **if and only
  if keys are per-agent** — the single highest-leverage recommendation to make to a customer.
- ⚠⚠ **Retention gap = the reason an independent evidence store must exist:** Stripe **Activity Logs**
  (programmatic access added 2026-04-22) retain **6 months**; **PCI DSS requires 12** (§6.10).
  **Stripe's own retention cannot satisfy PCI 10.5.1 for a card-handling customer.**
- ⚠ **[UNVERIFIED]** whether request logs expose the acting key **programmatically via API** (vs the
  Dashboard's per-key view). **Verify via the Stripe MCP before depending on it** — per-agent Stripe
  attribution is the load-bearing customer-facing claim.

### 6.9 CIEM prior art — how to frame a granted-vs-used finding

- **AWS IAM Access Analyzer unused-access findings** — three types (unused roles, unused keys/passwords,
  **unused permissions**). ⭐ **The finding schema is three fields and should be copied verbatim**
  (`UnusedPermissionDetails`): **`serviceNamespace`, `actions[]`, `lastAccessed`**. Findings have a
  lifecycle — active / resolved / **archived**, with **archive rules** for accepted risk. ⚠ Unused-access
  analysis needs a **separate analyzer** and is **billed per role/user/month** (external-access findings
  are free) — **continuous usage analysis has real cost; price accordingly.**
- **Microsoft Permission Creep Index (PCI)** — the most product-ready *presentation*: a single **0–100
  score** comparing granted vs exercised, bucketed low/medium/high, with drill-down.
  ⚠ **Status correction: Microsoft Entra Permissions Management is RETIRED — support ended
  2025-11-01.** The **metric** survives inside Defender for Cloud's CIEM. Cite the metric design, not
  the product. *That a hyperscaler killed its standalone CIEM is itself a strategic datapoint.*
- **GCP IAM Recommender** — compares total vs used permissions over a **90-day window** (configurable
  30/60), and ⭐ uses ML to **predict permissions likely needed in future**, avoiding the classic false
  positive of revoking a quarterly-cadence permission on day 91. Presents a **recommendation** (a
  concrete smaller role), not just a finding.

**The seven transferable rules:** (1) two sets, one delta, each independently defensible; (2) **the
window is a first-class configurable parameter — a finding without a stated window is unfalsifiable**;
(3) **`lastAccessed` is the killer field** ("never used" ≠ "unused since March"); (4) two altitudes —
a rollup score for the exec, an itemised list for the engineer; (5) **ship a remediation, not a
complaint** (→ our draft-PR seam); (6) **prioritise by reachable impact, not count** — Wiz: unused
admin on a prod DB with sensitive data ≫ a test account; for agents **unused Stripe *write* ≫ unused
Stripe *read***; (7) findings need archive/accepted-risk lifecycle or the customer drowns.

### 6.10 Tamper-evidence — the proportionate bar

**Separate the two properties.** Tamper-**evidence** = modification is *detectable* (hash chains,
Merkle trees, signatures, anchoring — cheap). Tamper-**proofing** = modification is *prevented* (WORM,
S3 Object Lock Compliance, independent custodian — expensive and rigid). Hash-chaining alone does not
stop a writer who controls the whole chain **unless the head is externally witnessed**.

**Compliance, honestly:**
- **PCI DSS v4.0 Req 10** — **10.3.2** logs protected from modification; **10.3.4** FIM/change-detection
  on audit logs; ⭐ **10.5.1 retain 12 months, 3 months immediately available.**
  ⚠ **VERIFICATION FLAG: corroborated only across QSA/vendor secondary sources — NOT fetched from the
  PCI SSC primary document (click-through licence). Older sources use the v3.2.1 number 10.5.5 for what
  is now 10.3.4. CONFIRM NUMBERING BEFORE THIS SHIPS** — a wrong requirement number is exactly what a
  customer's QSA notices.
  Useful implementation caveat: FIM should watch files that don't regularly change — **appending log
  data must not alarm**, or you get pure noise.
- **SOC 2** — genuinely outcome-based; **no prescriptive immutability control**. CC6.1 / CC7.2 / CC7.3 /
  CC8.1. Auditors want logs "stored separately from the systems generating them, with access restricted."
  The commonly cited 12-months/90-days-hot is **practitioner convention, not codified** — say so.

**Real vs theatre:**

| Real | Theatre |
|---|---|
| Logs in a **separate trust domain** from the system that generates them | Blockchain anchoring |
| Write-only credentials for the emitter | RFC 3161 on every individual record |
| Hash chain + periodically published root | Compliance-mode WORM before you have a retention policy |
| 12-month retention, 3 hot (PCI 10.5.1) | "Immutable" as a marketing adjective with no verifier shipped |
| **A verifier the customer can run themselves** | An integrity claim only your own product can check |

> ⭐ **The sharpest test: does the customer possess a tool that can independently detect tampering —
> INCLUDING TAMPERING BY US? If not, the integrity claim is unfalsifiable, and unfalsifiable is
> theatre.** AWS passes (`aws cloudtrail validate-logs`); most "immutable audit log" SaaS does not.

**Reference implementations:**
- ⭐ **CloudTrail log file integrity validation** — the best model to copy. SHA-256 hashing + SHA-256/RSA
  signing; **hourly digest files** referencing the prior hour's logs; **each digest contains the digital
  signature of the previous digest** (the chain); signature lives in **S3 object metadata**, not the body;
  ⭐ **digest files live in a SEPARATE FOLDER** from logs — *"enables you to enforce granular security
  policies and permits existing log processing solutions to continue to operate without modification"*
  (different access-control posture for evidence-of-integrity vs the evidence itself, zero disruption to
  consumers). Delivers: detect modification, detect **deletion**, and ⭐ **positively assert that no logs
  were delivered during a given period** — proving absence, usually the hard part, free.
  **Verification is customer-runnable via the AWS CLI.**
- ⚠ **Amazon QLDB is RETIRED** (support ended 2025-07-31; AWS recommends Aurora PostgreSQL, which
  **explicitly does not provide cryptographic verifiability**). **Strategic lesson: AWS could not
  sustain a managed cryptographic-ledger business — do NOT make a bespoke ledger DB a load-bearing
  dependency, and do not position the evidence store as one.** Surviving managed alternative: Azure SQL
  ledger.
- **Sigstore Rekor / Trillian** — append-only transparency log, SHA-256 binary Merkle tree, inclusion +
  consistency proofs, clients can ⭐ **"staple"** an inclusion proof next to the artifact. Rekor v2 moves
  to tile-based Trillian-Tessera. Sigstore also runs a **free RFC 3161 TSA**
  (https://github.com/sigstore/timestamp-authority) — the cheapest credible third-party timestamping.
  ⭐ **Stapled inclusion proofs are the strongest transferable idea:** every finding/PR/evidence artifact
  carries its own portable proof, verifiable **without trusting us** and without downloading the log.
  That is what turns "we have an audit trail" into "here is the trace, and you can check it yourself."

**Recommended tiers** — Tier 1 (days, ~free, non-negotiable): append-only by construction (INSERT-only
emitter role, corrections are compensating records); **per-record hash chain** (`prev_hash`,
`hash = SHA-256(canonical_serialization || prev_hash)`); ⚠ **canonical serialization, pinned and
versioned** (drift silently makes every historical hash unverifiable — the most common way homegrown
chains die); **evidence in a different trust domain from the writer**; ⭐ **a standalone verifier the
customer runs** (without it, everything above is theatre); **12-month retention, 3 hot**.
Tier 2 (when the first QSA asks): periodic **Merkle root per window** stored separately (CloudTrail's
separated-digest pattern), **signed** with KMS/HSM keys, **published where the customer can see but we
cannot silently rewrite** (a customer-owned bucket, or emailed to their security contact — the cheapest
possible witness, and what makes a full-chain rewrite by us detectable), **stapled inclusion proofs on
exports**. Tier 3 (only on contractual demand): S3 Object Lock **Governance** (never start with
Compliance — an accidental 7-year retention is genuinely unfixable), RFC 3161 on **roots not records**.
**Do not build:** a bespoke ledger DB, blockchain anchoring, per-record third-party timestamping.

> ⭐⭐ **The honest sentence for the ADR:** *tamper-evidence at Tier 1–2 means we can prove our records
> were not altered after we wrote them; it does not prove they were true when we wrote them.* The truth
> of the record rests on the fidelity of collection — and **a shared API key means the record cannot
> have been true about WHICH AGENT ACTED in the first place. No amount of cryptography downstream
> repairs an attribution that was never captured.**
> **That dependency — identity first, then permissions, then evidence — is the spine the ADR is built around.**

### 6.11 The gap, named

**Microsoft's "Least privilege for AI agents: identity, access, and tool binding"** (2026-07-16,
https://www.microsoft.com/en-us/security/blog/2026/07/16/least-privilege-for-ai-agents-identity-access-and-tool-binding/)
is the most authoritative treatment: agents as **first-class principals**, dedicated identities,
**tool binding** ("a curated and approved set of tools/actions" with "explicit allowlists for
high-impact operations"), task-based RBAC, multi-dimensional scoping, JIT elevation.

⭐ **But Microsoft does NOT discuss granted-vs-used analysis for agents.** Their answer is entirely
**preventive**. Everything else found in the space is preventive too (MCP RBAC, request-time authz,
OpenFGA per-tool checks, Claude permission policies).

> **Conclusion: "CIEM for agents" — retrospective, observed-usage-based narrowing of an agent's tool
> and credential surface — is an identified gap with NO mature product. The building blocks (MCP
> `tools/list` + `list_changed`, Stripe per-key request logs, IdP scope APIs, cloud IAM last-accessed)
> all exist and are all programmatically accessible. That is a defensible thing to build.**

### 6.12 Could-not-verify list from this stream

1. **PCI DSS numbering/wording (10.3.2, 10.3.4, 10.5.1)** — secondary sources only. **Confirm.**
2. **All over-privilege percentages** — vendor blogs, no methodology. Do not cite.
3. **Okta announcement date** — inconsistent fetch; GA 2026-04-30 is vendor-stated.
4. Commercial RFC 3161 TSA pricing — not found.
5. **AIP / IBCT** — individual submission + preprint, not a standard.
6. ⚠ **Whether Stripe exposes the acting key per-request programmatically via API** — Dashboard surface
   confirmed, API attribution **not**. **Verify via the Stripe MCP; a load-bearing claim depends on it.**

## 7. Findings — Stream H (standards + competitive) — COMPLETE

### 7.0 ⚠️⚠️ FOUR CORRECTIONS — earlier drafts of this ADR were wrong on all four

| Claimed | Reality |
|---|---|
| "EU AI Act high-risk **logging** obligations bit on 2026-08-02" | ❌ **The logging articles did NOT take effect.** **Regulation (EU) 2026/1744** (in force 2026-07-27) **deferred Articles 12 / 19 / 26(6) to 2 December 2027.** What went live 2026-08-02 is **Article 50 transparency only** — a *disclosure* duty, not a *record-keeping* duty. https://eur-lex.europa.eu/eli/reg/2026/1744/oj |
| "OWASP **LLM06** Excessive Agency / **LLM08**" | ❌ **Stale by six days.** The **2026 edition published August 2026**. **Excessive Agency is now `LLM03:2026`** (the biggest climb on the list); Vector & Embedding Weaknesses is now `LLM09:2026`. https://genai.owasp.org/download/56857 |
| "MITRE ATLAS **v5.4.0 (2026-02)** added agent tool credential harvesting" | ❌ **Date right, content wrong.** **AI Agent Tool Credential Harvesting is `AML.T0098`, added in v5.2.0 (2026-01-30).** v5.4.0 added T0104–T0108. **Current version is content `v2026.07`, published 2026-08-07** (16 tactics, 101 techniques, 77 sub-techniques, 68 case studies). |
| Implied: "agent runtime accountability is greenfield / unoccupied" | ❌ **Microsoft shipped it GA on 2026-05-01** as **Agent 365 at $15/user/month**, and **Purview audits agent-to-TOOL interactions**. The in-repo LANDSCAPE_2026-08.md "unoccupied" verdict predates/misses this and must be qualified. |

### 7.1 ⭐ The single most valuable citation in the entire research pass

**OWASP Agentic Security Initiative threat taxonomy, threat T8 = "Repudiation & Untraceability."**

> A standards body has made *"the agent acted and you cannot prove what it did"* a **named threat class
> in its own right** — not a missing control, a **threat**.

Corroborated independently by **CSA MAESTRO Layer-7**, which names the threat as "AI agents denying
actions they performed… due to the difficulty in tracing actions back to an AI agent."

**Two more quotable ASI mitigations (verbatim, ASI 2026 PDF, printed pages):**
- **ASI10 Rogue Agents, mitigation 1 (p37)** — effectively the product definition:
  > "**Governance & Logging:** Maintain comprehensive, **immutable and signed audit logs of all agent
  > actions, tool calls, and inter-agent communication** to review for stealth infiltration or
  > unapproved delegation."
- **ASI08 Cascading Failures, mitigation 10 (p32):**
  > "Record all inter-agent messages, policy decisions, and execution outcomes in **tamper-evident,
  > time-stamped logs bound to cryptographic agent identities.** Maintain lineage metadata for every
  > propagated action to support forensic traceability, rollback validation, and accountability."
- **ASI02, attack scenario 6 (p13)** — the argument for why existing tooling cannot see this:
  > "**EDR Bypass via Tool Chaining:** … **Because every command is executed by trusted binaries under
  > valid credentials, host-centric monitoring (EDR/XDR) sees no malware or exploit, and the misuse
  > goes undetected.**"
- **ASI03 (p15):** "Without a distinct, governed identity of its own, an agent operates in an
  **attribution gap** that makes enforcing true least privilege impossible."

⚠️ **ASI03 mitigation 6 (p17) is the sharpest counter-argument to a third-party product, and it is in
the primary source:** OWASP itself tells buyers to *"Evaluate Agentic Identity Management Platforms…
Examples include **Microsoft Entra, AWS Bedrock Agents, Salesforce Agentforce, Workday's ASOR model,
and similar emerging patterns in Google Vertex AI.**"*

### 7.2 ⚠️ OWASP explicitly classes logging as damage-limiting, NOT preventive

`LLM03:2026` Excessive Agency lists nine mitigations. **Monitoring (#8) and #9 appear under the
heading:** *"The following options **will not prevent** Excessive Agency but can limit the level of
damage caused."*

**Consequence: lead with prevention (least-privilege tools, complete mediation, HITL); position
telemetry as detection / forensics / attribution / replay. Claiming prevention contradicts the very
source we cite.** Other LLM03 mitigations worth using: #5 *"preserve the original user context and
authorization scope across chained tool or agent calls, rather than relying only on the permissions
of the calling agent"*; #7 complete mediation with a graduated **audit → warn → block → escalate**
policy; #8 *"Log and monitor the activity of LLM tools and downstream systems."*

**LLM09:2026** (vectors/embeddings) mitigation #6 is the strongest regulatory hook in either list:
*"Keep **immutable logs of retrieval activity** (tenant scope, query, returned IDs, similarity
scores)… treated as source-data leaks for breach assessment and notification under **GDPR Article
33**."*

**And the scope line that matters most** (LLM Top 10 2026, Project Leads' letter, p7):
> "**The moment that model becomes an actor, with tools it can call, memory it carries between
> sessions, and consequences it sets in motion downstream, the risk moves to the OWASP Agentic Top
> 10.**"

### 7.3 MITRE ATLAS — the agentic build-out and what is telemetry-only

- Current: content **`v2026.07` (2026-08-07)** — 16 tactics, **101 techniques, 77 sub-techniques**, 37
  mitigations, 68 case studies. https://github.com/mitre-atlas/atlas-data/releases/tag/v2026.07
- ⭐ **There is no separate agentic matrix.** Format v6.0.0 added a **`platform` field** with values
  **Predictive AI / Generative AI / Agentic AI / Enterprise** — *the agentic matrix is a filter, not a
  second product.* Build coverage views on `platform: Agentic AI`.
- **~40 agentic techniques added in ten months.** Highlights: v5.0.0 (2025-10-15, the **Zenity Labs**
  contribution, 14 entries incl. `T0080` context poisoning, `T0084` discover agent config, `T0085`
  data from AI services, **`T0086` exfiltration via AI agent tool invocation**); v5.1.0 added a **new
  Lateral Movement tactic `TA0015`** and **`T0094` Delay Execution of LLM Instructions**; v5.2.0
  (2026-01-30) added **`T0098` AI Agent Tool Credential Harvesting**, `T0099`, `T0101` data
  destruction via tool invocation; v5.5.0 added `T0110` AI Agent Tool Poisoning, `T0034.002` agentic
  cost harvesting, `T0084.003` **call chains**; v2026.07 split `T0110` into **`.000` definition /
  `.001` implementation / `.002` runtime response**.
- ⭐ **Detectable ONLY with runtime agent telemetry** (the attack runs via authorized tools, valid
  credentials, expected network paths — only the tool-call sequence, arguments and identity
  distinguish it): T0086, T0098, T0101, T0085, T0084 (incl. call chains), T0080, T0081, T0082, T0083,
  **T0094** (hardest — *the malicious act IS the temporal gap*), T0092, T0099, **T0110.002 Runtime
  Response** (definitionally runtime-only — MITRE created this sub-technique on 2026-08-07 *precisely
  because static supply-chain checks miss it*), T0034.002, T0103, T0109.
- ⚠️ **Do NOT over-claim:** T0105/T0106/T0107/T0112/T0113/T0097 are served by conventional telemetry —
  **EDR/CSPM own those**; agent telemetry only adds attribution. T0115/T0111 are pre-runtime (registry
  scanning).
- Mitigation **`AML.M0024` AI Telemetry Logging** is the direct one ("log AI agent tool invocations to
  detect malicious calls"), and ⭐ **was revised twice in 2026** — MITRE is actively re-scoping it.
  Also `M0029` **Human In-the-Loop for AI Agent Actions**, `M0030` restrict tool invocation on
  untrusted data.
- ⚠️ `atlas.mitre.org/mitigations/*` **404s** and the 717KB YAML exceeded fetch limits — M0024/M0029
  wording came from third-party mirrors. **Do not quote as MITRE-verbatim without re-checking.**

### 7.4 ⚠️ PCI — a significant correction to the earlier D7 draft

The relevant hooks are **10.2.1.2** ("all actions taken by any individual with administrative access,
**including any interactive use of application or system accounts**") + **10.2.2** (each entry records
**user identification**, event type, timestamp, success/failure, origination, affected resource) +
**10.5.1** (12 months / 3 hot). An autonomous agent on an admin-scoped service account in a CDE *is* an
entity taking administrative actions, and **10.2.2's user-identification field is precisely what agents
break.**

⚠️⚠️ **BUT — does Stripe change the answer? Yes, mostly in Isaac's favour, and this weakens PCI as the
trigger:**
- **Stripe Checkout / Payment Links with full redirect, or Elements in an iframe → SAQ A**, ~two dozen
  requirements, and **Requirement 10 is essentially not among them.** No CDE, nothing to log.
- **SAQ A-EP** (site controls the payment page) is far heavier and does pull in logging.
- March 2025: requirements **6.4.3** and **11.6.1** were **removed from SAQ A's requirement list but
  relocated into its eligibility criteria** — full redirect → don't apply; **iframe → they do.**

> **Verdict: a Stripe-redirect SAQ A merchant will not get Requirement 10 questions.** High rhetorical
> value, narrow actual applicability. **This must be corrected in the ADR — PCI is NOT the most likely
> hard trigger.**

⭐ **What IS highly citable — PCI SSC "AI Principles: Securing the Use of AI in Payment Environments"
(2025-09-11)**, the tightest product-spec-shaped language found anywhere:
> AI systems should be *"**Deployed so that the actions performed by the AI can be logged and
> monitored, and a (human) individual held responsible for those actions**"* and *"**logging should be
> sufficient to audit the prompt inputs and reasoning process used by the AI system.**"*

It further recommends treating AI systems as a potential **"malicious insider"** in threat analysis.
**Non-binding guidance — but it is our product spec, written by a payments authority.**
*(Separately: the March 2025 "Integrating AI in PCI Assessments" guidance governs how **QSAs** may use
AI — **do not cite it as a customer obligation.**)*
⚠️ v4.0.1 PDF is behind a click-through licence; numbering corroborated across ManageEngine / PCI DSS
Guide / Basis Theory — **not verbatim.**

### 7.5 ⭐ The actual #1 buying trigger: ISO/IEC 42001 arriving via the enterprise questionnaire (the SIG)

- **Control A.6.2.8 "AI system recording of event logs":** *"The organisation shall determine at which
  phases of the AI system life cycle event log recording is enabled."* ⚠️ iso.org 403 — text from
  ISMS.online; verify against the purchased standard.
  Note the control is deliberately **weak** (it obliges you to *decide* where logging is enabled, not
  to log anything specific) — **and that weakness is its commercial property: easy to certify against,
  hard to fail, which is why it spread fast.**
- ⭐ **The defensible adoption evidence (not vendor marketing):** the **Shared Assessments SIG
  Workbook added ISO/IEC 42001 references in its 2025-09-19 release**, carried into the **2026 SIG**,
  alongside AI-governance content covering "the whole AI lifecycle." **The SIG is the actual artefact
  enterprises email to vendors.** Corroborating: Vanta shipped an ISO 42001 framework and certified
  itself 2025-04-24; Drata announced its own certification Dec 2025.
- ⚠️ **Do NOT** put a named certified-company list in the ADR (single marketing blog), and **reject**
  "every meaningful questionnaire in H2 2026 includes AI governance" — the SIG citation is the
  defensible version.

**Why this ranks #1:** it is the only mechanism here that **blocks revenue today** (regulation creates
future liability; procurement creates a *now* blocker); the evidence is from a neutral industry body;
**A.6.2.8 gives the buyer a named control ID to demand evidence for** (frameworks without control IDs
don't generate asks); and the gap for a 60-agent fleet is a runtime system, not a document.

**#2 = SOC 2 Type II auditor asks in the current observation window** — the accelerant. There is **no
"SOC 2 for AI"** (AICPA has published no AI-specific TSCs as of mid-2026), but AI-fluent auditors are
mapping model lineage, **prompt/inference logs with PII redaction applied before logging**, drift
output and per-LLM vendor risk assessments onto **CC6 / CC7 / CC8** — uncodified, negotiable, **but it
lands inside the Type II period with no deferral to hide behind.**

**#3 = EU AI Act as ANXIETY, not obligation.** Art. 50 went live with **€15M / 3% of worldwide
turnover** penalties, which is why AI compliance is on buyers' legal desks *right now* — but Art. 50
requires **disclosure, not records**, and Arts. 12/19/26 are deferred to 2027-12-02. **Use the Act to
explain why buyers are asking; never as the obligation itself — the first competent counsel in the
room will correct you.**

Also on the Act: **Art. 12 is a *capability* requirement, not a content specification** — outside
biometric ID (Art. 12(3)) it never enumerates tool calls, prompts, model versions or agent decision
traces. **Anyone selling "Article 12 compliance" as a per-tool-call trace is over-reading the text.**
Art. 19/26(6) retention is *"at least six months."* **Would Isaac be in scope? Realistically no** —
the plausible capture path is Annex III **Point 4(b)** (monitoring/evaluating worker performance and
behaviour); a customer-support, sales or coding agent is not Annex III. **Zero harmonised standards
are cited in the OJ, so no Article 40 presumption of conformity exists today** — the best explanation
for the deferral.

**#4–8:** PCI SSC AI Principles (sharpest sentence, weakest bindingness, §7.4 scope problem) · CSA
**AICM v1.1 (2026-07-14, 247 control objectives, new Model Security domain)** feeding **CAIQ for AI** ·
**AIUC-1** · HITRUST (sector-bound) · NIST (most on-point intellectually, **none of it finished** —
this is roadmap justification, not 2026 revenue).

### 7.6 NIST — and one correction to propagate nowhere

- **AI RMF 1.0** relevant subcategories: **GOVERN 1.6** ("Mechanisms are in place to **inventory AI
  systems**"), **MEASURE 2.5** ("**Log input data** … whenever there is an attempt to use the system
  beyond its well-defined range"), ⭐ **MEASURE 2.8** ("**Instrument the system for measurement and
  tracking, e.g., by maintaining histories, audit logs**"), MANAGE 4.3.
- ⚠️ **Correction — do NOT propagate:** the circulating claim that **AI 600-1 "recommends logging
  detailed enough to reconstruct what a generative AI agent did, including tool calls."** **The full
  PDF text does not contain that language.** AI 600-1 predates the agent wave; its provenance emphasis
  is *content* provenance (watermarking/C2PA), not *execution* provenance. Also: AI 600-1 was issued
  under **EO 14110, rescinded January 2025** — current standing unverified.
- **CAISI AI Agent Standards Initiative (2026-02-17)** — three pillars, one being "AI agent security
  and identity." Agent-hijacking research: **400+ participants, 13 frontier models, 250,000+ attack
  attempts; at least one successful hijack against EVERY one of the 13 models; novel strategies hit
  81% task-hijacking success vs 11% baseline.** Recommended defence: *"**logging all external content
  the agent processes alongside the actions the agent subsequently takes — creating the audit trail
  needed to identify retrospectively whether environmental content influenced unexpected agent
  behavior**"* ⚠️ (this is CSA's framing of CAISI research, not a NIST control statement).
- **NCCoE "Software and AI Agent Identity and Authorization"** — initial public draft **2026-02-05**;
  extends OAuth 2.0, **SPIFFE/SPIRE** and **MCP** to agents; explicitly seeks input on "the
  identification, authorization, **auditing and non-repudiation** of AI agents."
- ⭐ **COSAIS (SP 800-53 Control Overlays for Securing AI Systems)** — five planned overlays including
  **"AI Agent Systems – Single Agent"** and **"Multi-Agent."** ⚠️ Only the Predictive-AI overlay has an
  annotated outline; **the two agent overlays have no publication date.** **This is the thing to
  watch** — when they land they define what "agent logging" means for anyone touching FedRAMP.

### 7.7 ⚠️⚠️ Competitive — the "unoccupied" verdict must be qualified: Microsoft already shipped it

**Microsoft Agent 365 — GA 2026-05-01, $15/user/month**, admin experience in the M365 admin center,
**multicloud reach beyond Microsoft's stack**. And **Purview Audit for Agent 365 is the most complete
shipped agent-action ledger found** (https://learn.microsoft.com/en-us/purview/ai-agent-365):
- *"When you create an agent instance for Agent 365, it's **automatically enabled for audit**"*
- ⭐ *"**Supported interactions: All agent-to-human, human-to-agent, agent-to-tools, and agent-to-agent
  interactions.**"* — **including agent-to-tool**
- `CopilotInteraction` carries `AgentId`, `AgentName`, `AgentVersion`, `AISystemPlugin`,
  `AccessedResources[]` with per-resource `Action` / `SensitivityLabelId` / `XPIADetected`, and
  `JailbreakDetected`. Full DLP / Insider Risk / eDiscovery / retention applies **to agents as if they
  were users**.
- **Capture is identity-anchored** (every instance holds an Entra Agent ID) — *structurally stronger
  than a network proxy: it doesn't matter where the traffic goes if the actor is an identity that logs.*
- ⚠️ **The pricing tell:** effective **2026-07-01, AI-agent discovery and posture for Foundry and
  third-party cloud agents requires an Agent 365 license** (moved off Defender CSPM). **Microsoft is
  monetizing exactly the cross-platform agent-visibility function a startup would sell.**

**The three tiers vendors conflate** (use this taxonomy): **DISCOVER** (inventory — capability, not
behaviour, ∴ not provable) · **GUARDRAIL** (inline allow/modify/block — provable only for traffic that
traverses it) · **OBSERVE/ACCOUNT** (durable, queryable, attributable record — the actual
accountability tier). *Almost every vendor claims all three; very few ship the third usably.*

| Vendor | Tier | Notes |
|---|---|---|
| **Zenity** | **OBSERVE — best independent.** Logs "messages, tool calls, retrievals, and handoffs between agents"; step-by-step forensics | **$125M Series C 2026-08-03**, ~$185M total, revenue tripled two years running. **Gartner: "the company to beat in AI agent governance" (April 2026).** ⚠️ **Capture architecture undisclosed — the biggest single hole in this research.** |
| **Obsidian** | **OBSERVE for agents inside SaaS** | ⭐ **Best-documented capture, two-pronged:** 200+ SaaS API integrations **plus a browser extension** that "captures real-time user and **AI agent activity, confirming what actually happened, not just what server APIs reported**." **$85M Series D 2026-08-04 at $1.1B.** |
| **Noma** | GUARDRAIL + partial observe | **Rides someone else's gateway** (Kong plugin, LiteLLM, Vercel AI SDK) — **does not own a data plane**. $100M Series B. **No forensic/audit surface published.** |
| **WitnessAI** | GUARDRAIL + explainability | $58M (2026-01-13). ⚠️ deployment model (proxy vs tap vs inline) unconfirmed |
| **Lakera → Check Point** | **GUARDRAIL only** — never an agent ledger | Completed 2025-11-11; ~$300M reported, **officially undisclosed** |
| **Prompt Security → SentinelOne** | DISCOVER + GUARDRAIL | Completed 2025-09-05. ⚠️ price genuinely ambiguous (~$180M vs ~$250M). **Prompt AI Agent Security launched RSAC 2026 — PREVIEW, not GA** |
| **Palo Alto (Protect AI + Portkey)** | GUARDRAIL + emerging observe | ⭐ **They bought the data plane: Portkey (AI Gateway) closed 2026-05-29**, becoming "the foundational AI gateway inside Prisma AIRS." **The single most important architectural signal in the landscape.** ⚠️ $650–700M for Protect AI is a **Jefferies estimate**, not disclosed |
| **Wiz (Google)** | **DISCOVER/posture** — its "runtime" is drift + suspicious-DNS anomaly detection, **not a tool-call ledger** | Google deal **closed 2026-03-11, $32B**. Wiz AI-APP 2026-04-22; Wiz MCP GA 2026-07-02 |

**Non-human identity was almost entirely acquired in 2026:** Astrix → **Cisco** (2026-05-04; plan is to
feed agent-activity intelligence **into Splunk**) · Oasis → **Cyera $1B agreed 2026-07-28** (⚠️ no
confirmation it closed) · Entro → **SailPoint** (completed 2026-06-29) · **CrowdStrike acquired SGNL
for $740M (2026-01-08)** and announced **SPIFFE-based agent identity with delegation context preserved
when an agent delegates to a sub-agent** · Okta **XAA is now an official MCP authorization extension**.
Still independent: **Token Security** (ships an "intent-based" model evaluating ***why*** an action is
taken) and **Britive** (patented **JIT ephemeral credentials created at runtime and destroyed when the
task ends**; ships an MCP Gateway issuing JIT scoped credentials on AWS AgentCore).

**MCP's structural gap, restated from the standards side:** *"MCP has a serious, rapidly-maturing
**authorization** story and essentially no **audit** story."* No protocol-level requirement that a tool
invocation be logged, attributed or made tamper-evident — and 2026-07-28 **deprecated the `Logging`
core feature outright**. Best gateway audit trail found: **Cloudflare MCP Server Portals** ("Cloudflare
Access logs the individual requests made using the tools in the portal", Logpush to SIEM). **December
2025: Anthropic donated MCP to the Agentic AI Foundation (Linux Foundation).**

**Platform-native audit — the commoditization check:**
- **AWS AgentCore:** ⚠️ *"By default, AgentCore outputs a set of span data for memory resources only.
  To record span data for your agents or gateway resources, you need to instrument your agent."*
  **CloudTrail sees `InvokeAgentRuntime` — one line. It does not see the 40 tool calls inside.**
- **Google Cloud:** architecturally most serious — **Agent Identity on SPIFFE**, non-shared,
  non-impersonable, no long-lived keys, audit showing both agent and **on-behalf-of** user identity.
  GA for Agent Runtime. ⚠️ Could not confirm tool calls with arguments reach Cloud Audit Logs vs only
  Cloud Trace.
- **OpenAI: weakest and retreating** — Audit Log API is ~51 event types, **all control plane, zero
  agent coverage**; and **OpenAI announced shutdown of Agent Builder and Evals (2026-06-03, effective
  2026-11-30)** — deleting the surface where governance would live.
- **Anthropic: best vocabulary, deliberately scoped out** — Agent SDK OTel spans nest subagents so
  **the full delegation chain is one trace**, `OTEL_LOG_TOOL_DETAILS=1` adds tool arguments, and docs
  say these "become a per-user audit trail you can forward to a SIEM" — **but the hosted Compliance API
  states outright: "The API does not log inference activities."**
- **ServiceNow AI Control Tower** is the closest existing *commercial* product to third-party agent
  accountability (deliberately cross-vendor, incl. "Audit Logging and Traceability") — but GRC-shaped,
  not tool-call-shaped, and gated behind being a ServiceNow customer.

### 7.8 Observability vendors — who markets security

- **Datadog is the only one with an actual security product**: **AI Guard** "evaluates prompts,
  responses, **and tool calls**… [and can] **block it before it can reach critical systems**"
  (⚠️ Limited Availability, GA unconfirmed); plus **Service Access Tokens / Workload Identity
  Federation** GA'd at DASH 2026 explicitly for "autonomous AI agents… without relying on long-lived
  shared credentials"; plus Agent Console inventorying Claude Code / Cursor / Copilot.
- **LangSmith** has the strongest *governance narrative*: an article-by-article EU AI Act mapping and
  ⭐ **audit logs emitted in OCSF v1.7.0 API Activity format with 400-day retention and documented SIEM
  forwarding** — a security-native schema choice. ⚠️ **But it covers admin/config writes only, not
  agent actions.** Right format, wrong scope.
- **Arize** — ⚠️ **correction: Arize was not acquired; it ACQUIRED Velvet (AI gateway) 2025-03-13.** Only
  pure-play with real runtime blocking (Guards).
- ⭐ **Langfuse (in our stack) — acquired by ClickHouse, announced 2026-01-16** (alongside ClickHouse's
  $400M Series D at ~$15B). MIT licence intact, self-hosting first-class. **Audit logs are
  Enterprise-only and admin-action-only.** ⭐ **Their own docs disclaim runtime security — the single
  most useful quote in the competitive set:** *"LLM Security can be addressed with a combination of —
  LLM Security libraries for run-time security measures — **Langfuse for the ex-post evaluation of the
  effectiveness of these measures**."*
- **Helicone — acquired by Mintlify 2026-03-03, now maintenance mode ("active feature development has
  ended"). Do not build on it.** **Traceloop → ServiceNow (~$60–80M, 2026-03-02).**

### 7.9 ⭐ IETF agent receipts — the emerging standard nobody is watching

**Seven individual drafts filed July–August 2026 alone.** The critical one:

**`draft-schrock-ep-authorization-receipts-10` (2026-08-06) — "Authorization Receipts for High-Risk
Agent Actions"** (https://datatracker.ietf.org/doc/draft-schrock-ep-authorization-receipts/). It is
almost a specification of this product, and names three gaps verbatim:
- the **action gap** — IAM authorizes sessions, not individual actions;
- the **accountability gap** — approvals are mutable database records;
- ⭐ the **verification gap** — **evidence must be auditable *outside the operator*.**

Mechanism: an enrolled approver signs an Authorization Context *before* execution; the resulting
**Trust Receipt** carries the action object, signatures, consumption record, and a **Merkle inclusion
proof against a signed log checkpoint**, verifiable **fully offline**, with enforced separation of
duties. Others: `draft-fane-opena2a-aip-02`, `draft-sharif-x509-agent-identity-profile-03`,
`draft-reece-wimse-cross-org-delegation-01`. ⚠️ **All individual submissions, none WG-adopted.**
⚠️ **OpenID Foundation agent-identity work could NOT be verified** — openid.net/specs shows none.

### 7.10 ⭐⭐ Convergence, and what survives commoditization

**Three shipped convergence points, not a trend piece:**
1. **Splunk AI Security Monitoring** (docs updated 2026-06-16) "integrates Splunk Observability for AI
   with **Cisco AI Defense**"; the `opentelemetry-instrumentation-aidefense` library adds a
   **`gen_ai.security_event_id` attribute to chat spans, enabling audit trails for every prompt and
   response against security guardrails.** ⭐ *An observability trace carrying a security event ID —
   one product, one schema, two budgets.*
2. **Datadog moving security-ward** organically off the installed tracer (distribution beats acquisition).
3. **Security platforms buying the observability data plane** — PANW/Portkey, ServiceNow/Traceloop,
   Cisco/Astrix→Splunk, CrowdStrike/SGNL.

> **Direction of travel: security is eating observability, not the reverse.** The observability
> pure-plays move only as far as *compliance narrative*; **agent observability is being commoditized
> into a sensor feed for a security control plane.**

⭐ **And crucially — nobody's "audit log" is an agent-action audit log.** Every one surveyed is
admin/config CRUD (Langfuse, LangSmith, OpenAI, Anthropic Compliance API) or ML lineage.
**Microsoft is the sole exception, and it got there from the identity plane, not the telemetry plane.**

**What survives commoditization:**

| Claim | Verdict |
|---|---|
| "We show you what your agents did" | ❌ **Already commoditized.** **Do not build here.** |
| "We inventory agents across your estate" | ❌ **Commoditized within 12 months** (Agent 365, ServiceNow, Wiz, Zenity, Noma, Astrix) |
| ⭐ **"Tamper-evident, portable, offline-verifiable evidence that a specific human approved a specific agent action, verifiable *outside the operator*"** | ✅ **Not shipped by anyone.** Every platform log is operator-controlled, mutable-by-the-operator, retention-capped (Purview non-Microsoft **180 days**; OpenAI ~30 days), and stops at that vendor's boundary |

**Three reasons that last row is defensible:** (1) the standards bodies **name the gap** — OWASP **T8**
and CSA MAESTRO Layer-7 both class un-attributable agent action as a threat in itself, and ASI08/ASI10
demand logs "**bound to cryptographic agent identities**" and "**immutable and signed**"; (2) **seven
IETF drafts in two months**, one of which names the **verification gap** as *"evidence must be auditable
outside the operator"*; (3) ⭐ **it is the one framing the platforms are structurally disincentivized to
build — an operator cannot credibly sell evidence designed to be verifiable *against* the operator.**
Reinforced by CSA: a compromised orchestrator controls its own audit trail, so you need "**external,
out-of-band monitoring… that does not rely on the orchestrator itself for log generation**."
**Corollary to state up front as a credibility asset, not a liability: self-reported agent telemetry is
not trustworthy evidence about that agent.**

**Also:** pure inline-proxy accountability is trivially defeated by an agent that doesn't route through
the proxy — **read every vendor's coverage claim as "of the traffic we see."** The defensible
architectures anchor on **identity** (Microsoft) or **reconcile independent evidence sources**
(Obsidian's browser-vs-API model).

### 7.11 Who eats this, and how fast

**Most likely absorber: Microsoft — and it has already substantially done it.** Four layers all GA:
identity (Entra Agent ID), inventory (Agent 365), **durable tenant-wide agent-to-tool audit**
(Purview), and framework-agnostic tracing (Foundry, covering LangChain/LangGraph/OpenAI Agents SDK).
**Assume 6–12 months to "good enough for most buyers," not 2–3 years.**
**Runner-up and technically more dangerous long-term: Google** (SPIFFE-based agent identity is the
architecturally correct primitive; also owns Wiz). **Also credible:** Palo Alto (owns the data plane,
can bundle into platform credits), CrowdStrike, Cisco, ServiceNow. **Least likely:** OpenAI (shutting
down Agent Builder) and Anthropic (Compliance API explicitly does not log inference).

**Pricing anchors (weak):** Microsoft Agent 365 **$15/user/month** is the only published
agent-governance price; Wiz ~$24k/yr for 100 workloads; Zenity/Noma/WitnessAI/Obsidian quote-only.
⭐ **There is no established per-agent pricing model — both a risk and an opening.**

### 7.12 Stream H could-not-verify list

⚠️ **Search budget exhausted (200/200)**; late verification was WebFetch-only.
**Do not propagate:** a "Langfuse $50M Series B March 2026" claim (contradicted by the ClickHouse
acquisition) · AI 600-1 "tool call logging" language (not in the PDF) · Docker MCP Gateway "90%
reduction in incidents" (marketing) · named ISO 42001 certificate-holder lists.
**Could not verify:** Zenity's capture architecture (biggest hole) · WitnessAI's deployment model ·
Noma's non-gateway capture path · ATLAS mitigation verbatim text (404 + oversized YAML) · PCI DSS
v4.0.1 verbatim (licensed PDF) · ISO 42001 A.6.2.8 normative text (iso.org 403) · AICPA's AI position
(site unreachable) · OpenID Foundation agent drafts (none found) · whether Google Cloud Audit Logs
carry tool-call detail · Snowflake Cortex Agents audit · Arize AX audit/RBAC docs · CAISI rename from
US AISI.
**Deal terms reported-only:** Check Point/Lakera ~$300M · SentinelOne/Prompt ~$180M vs ~$250M
(genuinely ambiguous) · PANW/Protect AI $650–700M (Jefferies estimate) · Cisco/Astrix ~$300M ·
SailPoint/Entro ~$200M · **Cyera/Oasis $1B agreed 2026-07-28, closure unconfirmed.**
**Date conflicts:** Entra Agent ID GA (April/May/June 2026 — say **"GA by mid-2026"**) · OWASP LLM Top
10 2026 (Aug 3/4/6 — say **"August 2026"**) · ATLAS v5.4.0 (trust the CHANGELOG/API: **2026-02-05/06**).

## 7. Open questions / could-not-verify

_pending_
