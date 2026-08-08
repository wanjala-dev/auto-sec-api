# AI Security Article Mapping — Taimur Ijlal, "5 AI Security Projects That Will Get You Hired in 2026" (2026-08-08)

**Status:** knowledge capture + adopt shortlist. Nothing here is implemented or scheduled; Henry
decides sequencing. This is the "gather knowledge" half of the loop, in the style of the wanjala
`AI_OBSERVABILITY_WEBINAR_INSIGHTS_2026-06-26.md` precedent.

**Source:** Taimur Ijlal, *"5 AI Security Projects That Will Get You Hired in 2026"* (Medium,
2026-08). Second Ijlal article brought into the system — ADR 0018 (judgment flywheel) already
grounds on his *"Why Every Cybersecurity Professional Needs a Self-Improving AI Agent"* piece.

**Pairs with:** the fork-source hardening plan
`wanjala-api-v2.0/api-v2.0/docs/plans/AGENTIC_SECURITY_HARDENING_2026-07-15.md` (P0-1…P2-9 —
note: that plan doc lives ONLY in the source repo, but its items SHIPPED here; see §2),
`docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md` (§3.4 AI-SPM), ADR 0009 (compliance evidence),
ADR 0013 (contextual risk), ADR 0018 (drills), ADR 0019 (SAST pillar — the newest ScannerPort
worked example), `docs/product/STATE_AND_VISION.md`.

**Two lenses, mapped explicitly throughout:**
- **Lens A — securing OUR OWN agentic system.** We ship an AI SOC; its own AI security must be
  exemplary ("this will be probed by hackers" is CLAUDE.md canon).
- **Lens B — PRODUCT opportunities.** What customers would pay for. Roadmap candidates only —
  foundations-first is the standing rule (harden Tom's real-use loops before breadth).

---

## 0. The one-line thesis

> The article's five "portfolio projects" (red-team lab, secure RAG, secured agent, AI monitoring
> lab, governance assurance) are, for Auto-Sec, mostly a **description of what we already shipped**
> — the SEE-199…207 hardening wave built projects 2 and 3 nearly verbatim. What the article adds
> is the frontier we have NOT crossed: we **defend** our agent at every layer but we never
> **attack the assembled system**, and we **log** all AI telemetry but run **no security
> detections over it**. Attack-your-own-agent + detect-over-your-own-AI-telemetry are the two
> adoptable gaps — and the same two ideas are our most natural AI-SPM product wedge.

---

## 1. Insight map (quick scan)

| # | Article idea | Lens A (our own AI) | Lens B (product) |
|---|---|---|---|
| 1a | Adversarial probe catalogue (injection, jailbreak, encoding evasion, leakage) run repeatably | **Have (partial)** — `red_team_v1` corpus, 16 cases, 5 categories | — |
| 1b | External scanner (Garak/PyRIT/Promptfoo) against the deployed app | **Net-new — ADOPT #1** | **Net-new — the AI-SPM scanner pillar (roadmap)** |
| 1c | Planted fake secret as the attack objective (canary) | **Net-new — ADOPT #3** | Feeds the same pillar |
| 1d | Wire tests into CI, rerun on model/prompt/guardrail change | **Have (partial)** — eval harness runs; scan-regression is always-on, LLM-judge is env-gated | — |
| 2a | RAG data-flow diagram with trust boundaries | **Sharpens — ADOPT #5** (no DFD artifact exists) | Evidence artifact for ADR 0009 later |
| 2b | Query-time access control / retrieval filtering | **Have** — role-scoped retrieval (SEE-199) | — |
| 2c | Tenant isolation | **Have** — workspace_id pinned at SQL (constitutional) | — |
| 2d | Document trust labels + data-vs-instructions separation | **Have (partial)** — binary `untrusted` flag + planner framing | — |
| 2e | Output validation / poisoned-content cannot drive actions | **Sharpens — ADOPT #4** (flag never escalates the tool gate) | — |
| 3 | Secure an agent that takes actions ("the model was fooled and it did not matter") | **Have — our strongest overlap** (SEE-201/202/203 + sign_off + provenance) | Already product: the governance agent narrates it |
| 4 | AI security monitoring/detection lab over AI telemetry | **Sharpens — ADOPT #2** (telemetry rich, zero security detections) | **Net-new** — shadow-AI detection over customer logs (roadmap) |
| 5a | AI system inventory / risk register / NIST AI RMF mapping | **Have (partial)** — governance agent covers OUR fleet only | **Net-new** — customer AI estate governance (roadmap, ADR 0009 lane) |
| 5b | Traceability of one finding: attack → risk → control → evidence → ticket → retest | **Have (mostly)** — finding → board card → draft PR → provenance chain | ADR 0009's exact thesis ("provenance is the product") |

---

## 2. Ground truth: the hardening plan SHIPPED here (verified in code, 2026-08-08)

The article's projects 1–3 overlap the PANW/OWASP-derived hardening plan (P0-1…P2-9). Status in
**this** repo, greps verified:

| Item | Status | Evidence (autosec paths) |
|---|---|---|
| P0-1 role-scoped RAG (SEE-199) | **Shipped** | `components/knowledge/domain/value_objects/retrieval_sensitivity.py`, `components/knowledge/tests/unit/test_role_scoped_retrieval.py` |
| P0-2 indirect-injection defense (SEE-200) | **Shipped (2 of 3 layers)** | Index-time heuristic: `components/knowledge/domain/value_objects/injection_scan.py` (stamped in `pgvector_workspace_index_adapter.py`); planner untrusted-content framing: `components/agents/tests/unit/test_planner_injection_grounding.py`, chunk `untrusted` flag threaded in `components/agents/infrastructure/services/deep_service.py:135,273`. **Layer 3 (output-side guard) NOT shipped — see §4.4** |
| P0-3 autonomous service principal (SEE-201) | **Shipped** | `components/agents/tests/integration/test_ai_service_principal.py` |
| P0-4 kill switch (SEE-202) | **Shipped** | `components/agents/application/policies/ai_kill_switch.py`, `set_ai_kill_switch_use_case.py`, owner/admin-gated `POST /ai/agents/kill-switch/` (`test_ai_kill_switch_endpoint.py`), `feature.ai_kill_switch` seeded in `seed_feature_flags.py` |
| P1-5 risk-tiered tool ladder (SEE-203) | **Shipped** | `components/agents/application/policies/tool_risk.py` — `read`/`reversible_write`/`irreversible`, autonomous cap, HITL for irreversible; `@tool(risk=...)` live (posture agent tags `risk=ToolRisk.READ`); `test_tool_risk_gate.py` |
| P1-6 MCP scoping (SEE-204) | Inherited | Denylist referenced by the red-team suite; autosec's tool surface is code-first (no customer-facing MCP yet) |
| P1-7 online eval over traces (SEE-205) | **Shipped** | `components/agents/infrastructure/adapters/actions/detectors/run_quality.py` + `test_run_quality_detector.py`; rubric middleware landed flag-gated (`test_rubric_middleware_wiring.py`); run telemetry stamps (`test_run_telemetry_stamp.py`) |
| P2-8 agent registry | Design-only (as planned) | — |
| P2-9 red-team suite (SEE-207) | **Shipped** | `components/agents/tests/prompt_eval/test_red_team.py` + `datasets/red_team_v1.json` (16 cases: injection, jailbreak, exfiltration, goal_manipulation, benign_control) |

Also standing (relevant to projects 3–5): DeepRun/DeepRunLog full trace store
(`infrastructure/persistence/ai/agents/models.py:344,380`), Langfuse tracing behind a port
(`components/agents/application/ports/tracing_port.py`, `adapters/tracing/langfuse.py`),
owner-only run-detail authz with redacted list projection AND WS-envelope redaction
(`test_deep_run_ws_envelope_redaction.py` — the previously tracked WS tool-IO leak now has
coverage), the read-only `ai_governance_agent`
(`components/agents/infrastructure/adapters/langchain/agents/ai_governance_agent.py` — tool
usage by risk tier, capability grants, HITL ledger, credential surface, kill-switch state; the
kill switch is deliberately NOT a tool), the `honeypot` trap app mounted at `/admin/`
(`api/urls.py:32`), the immutable `audit` context, and the `sign_off` approval gate.

**Hygiene note:** the hardening plan doc itself lives only in the fork-source repo. Its items
shipped here under SEE- ids but the narrative is un-findable from autosec's `docs/`. This mapping
doc now carries the status table above; if the plan is ever extended, extend it HERE.

---

## 3. Per-project mapping

### 3.1 Project 1 — Automated AI red-teaming lab

**Article:** attack an LLM app repeatably — NVIDIA Garak (probe catalogue), Microsoft PyRIT
(orchestrators/scorers/converters), Promptfoo (light on-ramp); a planted fake secret as the
objective; a deliberate attack catalogue (direct injection, jailbreak personas, system-prompt
extraction, encoding evasion); findings mapped to OWASP LLM01/02/07; tests wired into CI so they
rerun when the model/prompt/guardrails change.

**Lens A — what we have.** The *catalogue* and the *CI rerun* halves exist: `red_team_v1` is a
versioned 16-case corpus across the article's exact categories, each case naming the defence layer
that should stop it; the deterministic half (does `is_injection_suspected` flag it?) runs always-on
as a regression net, and the LLM-judge pass runs env-gated like the other quality evals. Prompt
changes ride the PromptRegistry version discipline (`planner.system` v8 cited in the corpus), so
"rerun when the prompt changes" is structurally true.

**Lens A — the gap (the sharpest insight in the whole article).** Everything we have tests the
**defence function** or the **planner in isolation**. Nothing attacks the **assembled, deployed
system** — the real agent-chat endpoint with the real orchestrator, real retrieval, real tool
gates. "The model was fooled and it did not matter" (project 3's thesis) is only *provable*
end-to-end. Garak v0.15.0 (2026-05) ships exactly this shape: an **agent-breaker probe** for
tool-driving agents, a multi-turn GOAT probe, and a system-prompt-extraction probe — pointed at an
HTTP endpoint. Apache-2.0, NVIDIA-maintained, official image → fits `pin-versions.md` (pin a
digest) and the improve-don't-replicate precedent (official image + native CLI, the Trivy/Prowler
shape, not a custom wrapper).

**Adopt (Lens A):** #1 in §5 — a scheduled Garak harness against our own deployed agent-chat
surface, findings landing as detector-cycle entries. NOT a parallel eval system: `red_team_v1`
stays the canonical corpus for the layers it covers; Garak covers the assembled-system layer the
corpus structurally cannot.

**Lens B:** the same harness, generalized, is the AI-SPM scanner pillar — §6.1.

### 3.2 Project 2 — Threat-modeled secure RAG

**Article:** DFD with trust boundaries; attack indirect injection via retrieved data,
cross-tenant leakage, poisoning, context exfiltration, embedding weaknesses; map to OWASP
LLM01/02/08 + MITRE ATLAS; controls = document trust labels, retrieval filtering + query-time
access control, tenant isolation, output validation, data-vs-instructions separation.

**Lens A — largely Have.** This project is close to a checklist of SEE-199/200:

| Article control | Our status |
|---|---|
| Tenant isolation | **Have** — `workspace_id` pinned at SQL on every chunk (constitutional §5.8 inheritance) |
| Query-time access control | **Have** — role-scoped retrieval, `retrieval_sensitivity` tiers, member vs admin filtering at SQL |
| Data-vs-instructions separation | **Have** — planner frames retrieved chunks as untrusted data (`test_planner_injection_grounding.py`) |
| Document trust labels | **Partial** — one binary `untrusted` flag from the index-time heuristic. The article's framing is a *label spectrum* (source provenance: operator-authored vs customer-log-derived vs uploaded doc). Cheap sharpening when a real need appears; the binary flag is honest for today's two sources |
| Poisoning blast-radius | **Have (inherited)** — opt-in indexing, per-workspace quota, failure circuit-breaker |
| Output validation | **Gap** — see §4.4 / adopt #4: the `untrusted` flag reaches the planner prompt but never escalates the tool gate |
| Embedding weaknesses (inversion/similarity abuse) | **Not addressed — deliberate non-adopt** (§7): research-grade attack, pgvector is not an exposed surface |

**Sharpens:** no DFD/trust-boundary artifact exists anywhere in `docs/`. Half a day, high leverage
three ways: onboarding, the ADR 0009 evidence pack (auditors ask for exactly this diagram), and it
makes the §4.4 taint gap visually obvious. Adopt #5.

### 3.3 Project 3 — Secure an agent that takes actions

**Article:** demonstrate injection making an agent misuse a tool, then re-architect: dedicated
agent identity (not the user), tool allowlists + least privilege, short-lived scoped creds, HITL
for high-impact actions, input trust labels, complete tool-call logging, emergency revocation.
Thesis: *"the model was fooled, and it did not matter."*

**Lens A — our strongest overlap. Have, nearly item-for-item:**

| Article control | Ours |
|---|---|
| Dedicated agent identity | Autonomous service principal (SEE-201) — recorded on DeepRun/DeepRunLog/AIAction |
| Tool allowlists + least privilege | Code-first tool registry, per-tool `@requires_role`, per-agent capability grants |
| HITL for high-impact actions | `ToolRisk.IRREVERSIBLE` → approval-gated; autonomous runs capped at `reversible_write` and must raise a finding instead; `sign_off` context for high-risk actions |
| Short-lived scoped creds | AWS = STS assume-role (short-lived by construction). VCS = encrypted long-lived token scoped by `repo_allowlist` — the one soft spot; fine-grained short-expiry tokens are a later hardening, tracked not urgent |
| Input trust labels | `untrusted` chunk flag (partial — see §4.4) |
| Complete tool-call logging | DeepRunLog per-call trace + Langfuse + AIAction + board-card provenance (every AI action posted to the kanban — the standing HARD principle) |
| Emergency revocation | Kill switch (global flag + endpoint) + per-agent disable + per-workspace `ai_teammate_enabled` |

**Net effect:** we could write the article's project-3 "professional assessment" about our own
system today, with file citations. That is a positioning asset (see §8) — none of the AI-SOC
competitors publish their own agent's containment architecture.

**Lens B:** the `ai_governance_agent` already narrates this to the operator. The product gap is
that it governs *our* fleet only — the customer's AI estate is §6.3.

### 3.4 Project 4 — AI security monitoring / detection lab

**Article:** telemetry stream (prompts, responses, retrievals, tool calls, identity events,
blocked actions) → detections: repeated jailbreak attempts, secrets in prompts (shadow-AI leak
path), anomalous retrieval volumes, unexpected/denied tool calls, new data-source access,
abnormal multi-step agent behavior, exfiltration via model output; tuned FP rates; incident
playbook end-to-end.

**Lens A — the telemetry exists; the detections do not.** We have every stream the article lists:
DeepRunLog (prompts, tool calls, tokens, latency), run telemetry + rubric verdicts, injection-scan
flags stamped per chunk, `tool_risk_refusal` denials, kill-switch flips, login activity, the
honeypot. And we have exactly ONE detector over any of it — `run_quality` — which is a *quality*
signal, not a *security* signal. Verified today: `is_injection_suspected` has zero consumers
outside the indexer and tests — a workspace whose documents get flagged ten times this week (someone
probing the RAG surface) produces **no finding, no notification, nothing**. Denied irreversible
tool attempts likewise vanish into the refusal string.

This is the article's most actionable idea for us, and it lands on a proven ~1-day seam (the
finding-source recipe: detector registry entry → `persist_finding_as_task` → board → routable to
triage). Detections, in priority order:

1. **Injection-flag spike** — N flagged chunks per workspace per window (probing signal).
2. **Denied tool-call attempts** — an autonomous run repeatedly hitting the irreversible gate is
   the "unexpected tool call" detection verbatim.
3. **Kill-switch / capability-grant changes** → notification-worthy governance events (partially
   covered by the SOC notification bridge; make it a finding, not just a toast).
4. **Anomalous retrieval volume** per principal (context-exfiltration signal; needs a retrieval
   counter — small schema addition).

Detections feed the **existing** Finding SSOT — dogfooding the product on our own AI telemetry.
This IS the article's monitoring lab, productized. Adopt #2.

**Lens B:** the same detection vocabulary pointed at *customer* logs = shadow-AI discovery
(LLM-API egress in CloudTrail/app logs, secrets-in-prompts where prompt-level telemetry exists).
Roadmap — §6.2.

### 3.5 Project 5 — AI security governance assurance

**Article:** AI system inventory (owner/purpose/model/data class/risk tier), risk register,
control mapping to NIST AI RMF + GenAI Profile + OWASP LLM Top 10 + MITRE ATLAS, evidence
register, executive dashboard; the elevating detail = TRACEABILITY of one finding:
attack → risk → control → evidence → ticket → retest.

**Lens A — Have (mostly), by architecture rather than by artifact.** The traceability chain the
article calls the differentiator is our standing pipeline: finding (attack) → contextual-risk
rank (ADR 0013 = risk) → triage with grounded verification (control) → provenance events + board
card + draft PR (evidence + ticket) → rescan/`last_seen` lifecycle (retest). ADR 0009 names the
thesis outright: *"provenance is the product"* — first-party evidence stamped at generation,
which aggregators (Vanta/Drata) structurally cannot do. What we do NOT have: a formal AI *system
inventory* / risk-register artifact for our own AI (the governance agent reports dynamic state,
not a register), and no NIST AI RMF control mapping anywhere. Framework currency (2026-08):
MITRE ATLAS v5.4.0 (2026-02) added agentic techniques (agent tool credential harvesting, etc.);
NIST CAISI launched an AI Agent Standards Initiative 2026-02 with deliverables later in 2026 —
i.e., the governance frameworks are moving toward exactly the agentic surface we already govern.

**Lens A adopt-lite:** fold a minimal self-inventory + OWASP/ATLAS control mapping into the §3.2
DFD one-pager (adopt #5) rather than building a register system. **Non-adopt** for the executive
AI-governance dashboard now (§7).

**Lens B:** customer-facing AI governance pack = §6.3, sequenced behind the ADR 0009 comply lens.

---

## 4. What this changes in the hardening plan's priorities

The P0/P1 hardening wave is **done** (P2-8 design-only as intended). The article reframes what
"next" means for our own AI security — from *build defences* to *continuously attack and monitor
the defences*:

1. **New top item: attack the assembled system** (adopt #1 + #3). The red-team suite exercises
   `is_injection_suspected` directly; nothing exercises orchestrator → retrieval → tool-gate as
   deployed. This is the successor to P2-9, not a change to it.
2. **New second item: security detections over AI telemetry** (adopt #2). P1-7 (SEE-205) shipped
   the *quality* half of "online eval"; the article shows the *security* half is missing and
   cheap (existing detector seam).
3. **Close the P0-2 remnant (§4.4 / adopt #4):** the plan's output-side guard — "before any tool
   executes an irreversible action with arguments derived from retrieved content, force HITL" —
   was layer 3 of the SEE-200 deep fix and did not ship. Today `untrusted` influences the planner
   prompt only. The deep fix is taint propagation: chunks marked `untrusted`/`scan-flagged` that
   feed a tool call escalate the effective ToolRisk tier (e.g. `reversible_write` → approval
   required) instead of relying on the model having read the framing. This is precisely the
   article's "input trust labels" control done properly — enforcement, not prompting.
4. **No re-prioritization of P2-8** (agent registry): still fleet-scale, still design-only.

---

## 5. Prioritized adopt shortlist (Lens A — our own system)

| # | What | Effort | Where it lands |
|---|---|---|---|
| 1 | **Garak harness against our own deployed agent-chat surface.** Pinned-digest official image (Apache-2.0; v0.15.0 2026-05 has agent-breaker + GOAT + system-prompt-extraction probes) run as a scheduled K8s Job (ADR 0006 substrate precedent) against a dedicated red-team workspace; results normalized into detector-cycle findings (informational first; gate later once FP-tuned). | ~2–3 days | `components/agents` detector seam + a scan-job manifest in auto-sec-infra; corpus stays `red_team_v1` for the layers it owns |
| 2 | **AI-telemetry security detections feeding the Finding SSOT** — injection-flag spikes, denied irreversible tool attempts, kill-switch/capability-grant events; anomalous retrieval volume second (needs a counter). | ~1 day per detection (proven finding-source recipe) | `components/agents/infrastructure/adapters/actions/detectors/` |
| 3 | **Canary-secret exfiltration objective**: plant an admin-tier canary chunk in the red-team workspace; assert no member query, no autonomous run, and no assembled-system probe (via #1) ever emits it. Turns "role-scoped retrieval works" into "exfiltration provably fails end-to-end." | ~1 day | prompt_eval + the #1 harness objective |
| 4 | **Taint propagation to the tool gate** (the un-shipped SEE-200 layer 3): untrusted-derived tool arguments escalate the effective ToolRisk tier / force HITL. Enforcement, not prompt-trust. | ~2–3 days | `tool_risk.py` + deep_service grounding metadata → orchestrator gate |
| 5 | **RAG/agent DFD + trust-boundary one-pager** with OWASP LLM01/02/08 + ATLAS mapping and a minimal AI self-inventory. Docs-only; triple duty (onboarding, ADR 0009 evidence pack, makes #4's gap visible). | ~0.5 day | `docs/architecture/` |

Suggested order: 5 → 2 → 3 → 1 → 4 (cheapest-to-deepest; 1 and 4 are the real engineering).

---

## 6. Product opportunities (Lens B — roadmap candidates, NOT now-work)

Foundations-first stands: Tom's real-use loops (AWS connect+scan, GitHub connect+scan, draft-PR)
outrank all of these. Recorded so the wedge is named when sequencing allows:

1. **AI-security scanning pillar (AI-SPM red-teaming).** A Garak-engine scanner behind the ONE
   `ScannerPort` (`components/shared_kernel/application/ports/scanner_port.py`) — same
   official-image + native-JSON shape as Trivy/Prowler/Opengrep — probing *customers'* AI
   endpoints for injection/jailbreak/leakage, findings into the SSOT, triage → remediation loop
   attached. Consent boundary mirrors ADR 0010's `repo_allowlist` (an `ai_endpoint_allowlist`);
   ADR 0019 is the freshest template for "new pillar behind the port." Differentiator vs
   point tools: findings land in the same graph/board/provenance pipeline as cloud + code
   findings — one SSOT, another lens. Adjacent validation: Lens-A adopt #1 IS the dogfood of this
   pillar. **Do not start before an ADR + an operator-validation pass.**
2. **Shadow-AI discovery over customer logs.** Detection vocabulary from §3.4 pointed outward:
   LLM-API egress (OpenAI/Anthropic/Bedrock endpoints) in CloudTrail/app logs → "unsanctioned AI
   usage" findings; secrets-in-prompts where the customer's own telemetry carries prompt bodies.
   Rides the existing LogSourcePort ingest + detector seam — no new substrate.
3. **Customer AI governance pack (comply-lens extension).** Extend the governance agent's
   vocabulary to the customer's AI estate: inventory, risk register, NIST AI RMF / GenAI Profile +
   ATLAS control mapping, first-party evidence via ADR 0009's envelope. Sequenced strictly behind
   the comply-lens build itself; framework tailwind is real (NIST CAISI agent-standards initiative,
   2026-02).

**Promptfoo note (research-grounded, 2026-08-08):** OpenAI acquired Promptfoo 2026-03-09 (to fold
into its Frontier agent platform; open-source continues under current license). For a neutral
security product, building our customer-facing red-team pillar on an OpenAI-owned engine is a
vendor-alignment risk Garak (NVIDIA, Apache-2.0, model-agnostic) doesn't carry. PyRIT (Microsoft,
build-your-own orchestration framework) is a candidate *second* engine if the pillar ever needs
multi-turn attack depth — same multi-engine pattern as Trivy+Prowler+Opengrep.

---

## 7. Explicit non-adopt list

| Article idea | Why not |
|---|---|
| **PyRIT as our Lens-A harness** | It's a framework, not a scanner — you author orchestrators/scorers yourself. Our corpus + Garak covers the need; adopting PyRIT now duplicates the eval harness (dry-reuse violation). Revisit only as engine #2 of the product pillar. |
| **Promptfoo in CI** | Duplicates the existing prompt_eval harness (canonical eval seam — one per concern), and post-acquisition it's OpenAI-owned infrastructure; wrong dependency for a neutral security product's own CI. |
| **Embedding-weakness defenses (inversion/similarity abuse)** | Research-grade attack class; pgvector is not an exposed surface (no embedding API, workspace-pinned at SQL). No named problem to fix — gold-plating per improve-dont-replicate §5. |
| **Executive AI-governance dashboard (our own)** | The governance agent + HUD already narrate kill-switch/risk-tier/HITL state on demand. A standalone exec dashboard is surface-building ahead of operator pull — the dashboard-fatigue counter-signal in SECURITY_POSTURE_VISION §8 applies. |
| **Standalone risk-register system for our own AI** | An artifact (in adopt #5's one-pager) suffices at our fleet size; a register *system* is P2-8 fleet-scale territory, design-only by standing decision. |
| **The article's "portfolio assessment report" framing** | It's a hiring-artifact deliverable. Our equivalents are ADRs + this mapping + (later) ADR 0009 evidence packs — no new report genre. |

---

## 8. Mom-test outreach flags (context only — outreach NOT drafted here)

Henry is drafting outreach to the author; things in this article that sharpen that conversation:

- **This is the second Ijlal article the system has absorbed** (ADR 0018 grounds on his
  self-improving-agent piece). His two themes — capture judgment, secure the agentic layer — map
  to our two most differentiated tracks (Remediation Memory / judgment flywheel; the SEE-hardening
  + governance agent).
- **His project 4 + 5 are literally our product thesis** — the "monitoring lab" is our detector
  cycle + Finding SSOT; his traceability chain (attack → … → retest) is ADR 0009's provenance
  envelope almost clause-for-clause. Strong common ground for a non-pitchy conversation.
- **Good mom-test questions live in his reader base:** which of the five projects do readers
  actually attempt, where do they stall (tooling? target app? interpreting results?), and do
  working security teams ask for these as *services/products* rather than portfolio pieces —
  direct demand signal for the §6.1 AI-SPM pillar before we ever build it.
- **Honest credibility artifact:** we can state that projects 2 and 3 describe controls we run in
  production, with code-level receipts (§2's table) — rare, checkable, non-marketing.

---

## 9. Tool/framework currency (research citations, 2026-08-08)

- **Garak** — NVIDIA, Apache-2.0, actively maintained; v0.14.0 (2026-02) redesigned reports +
  JSON config; **v0.15.0 (2026-05)** added multi-turn GOAT probe, **agent-breaker probe** (attacks
  tools available to LLM agents), system-prompt-extraction probe, ModernBERT refusal detector.
  (github.com/NVIDIA/garak; garak.ai; appsecsanta.com/garak, accessed 2026-08-08)
- **PyRIT** — Microsoft AI Red Team; orchestration framework (building blocks: orchestrators/
  scorers/converters), multi-turn attacks (Crescendo, TAP); expertise-heavy vs scanner-style
  tools. (promptfoo.dev/blog/promptfoo-vs-pyrit; qawerk.com/blog/llm-red-teaming-tools)
- **Promptfoo** — acquired by **OpenAI, announced 2026-03-09** (TechCrunch, CNBC, Bloomberg,
  openai.com/index/openai-to-acquire-promptfoo); folded into OpenAI Frontier; open-source
  continues under current license per OpenAI's statement.
- **MITRE ATLAS** — v5.4.0 (2026-02): 16 tactics / 84 techniques / 56 sub-techniques; agentic
  expansion began 2025-10 (14 agent-focused techniques, Zenity collaboration), 2026 updates add
  agent tool credential harvesting et al. (zenity.io; vectra.ai/topics/mitre-atlas)
- **NIST** — AI RMF 1.0 (2023) + Generative AI Profile (NIST-AI-600-1, 2024) remain current;
  NIST CAISI **AI Agent Standards Initiative launched 2026-02**, agent-runtime governance
  deliverables expected later in 2026. (speakeasy.com/resources/ai-security-frameworks)
