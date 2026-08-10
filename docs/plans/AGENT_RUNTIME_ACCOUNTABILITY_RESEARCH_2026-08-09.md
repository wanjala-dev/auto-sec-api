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

## 3. Findings — Stream A (our substrate)

_pending_

## 4. Findings — Stream B (our ingestion spine)

_pending_

## 5. Findings — Stream C (the capture problem)

_pending_

## 6. Findings — Streams D–H

_pending_

## 7. Open questions / could-not-verify

_pending_
