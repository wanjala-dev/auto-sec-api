# Loop Engineering Review — Webinar vs. Current Auto-Sec State + Gap List

**Date:** 2026-07-23. **Status:** Review + actionable gap list (no code in this PR — docs only).
**Companion to:** [`LOOP_ENGINEERING_SELF_IMPROVEMENT_2026-07-19.md`](./LOOP_ENGINEERING_SELF_IMPROVEMENT_2026-07-19.md)
(#48 — the phased design). This doc reconciles that design with the LangChain **loop-engineering**
webinar and records **what is actually true in the code today** (git-verified), then a prioritized
list of what to action next.

**Sources:** LangChain, [*The Art of Loop Engineering*](https://www.langchain.com/blog/the-art-of-loop-engineering);
[deepagents `RubricMiddleware`](https://docs.langchain.com/oss/python/deepagents/rubric); the webinar
Q&A (memory design, eval-engineering, human-in-the-loop, context-rot).

---

## 1. The yardstick — the four loops

> *The advantage is not just the agent you build to automate work, but the loops you build around it.*

| Loop | What it is | "Engineering" at this level |
|---|---|---|
| **L1 Agent loop** | model calls tools until the task is done | give the model the **right tools** + **right model** (match intelligence to task complexity/cost) + tool descriptions it actually uses |
| **L2 Verification loop** | a **grader** scores output against a **rubric**; on fail, re-inject **per-criterion feedback** and rerun, **bounded** | pick clear/verifiable criteria; cheap grader tier; cap iterations |
| **L3 Event-driven loop** | **triggers** (cron/webhook/Slack/email) fire the agent; the run updates a real system | the integrations layer is the product — an agent nobody can trigger has no value |
| **L4 Hill-climbing loop** | an **analysis agent** reads production **traces** → rewrites the **harness** (prompts, tools, skills, memory) and commits back | needs **evals you trust** to merge harness changes safely; the outer loop reaches *inside* the inner ones |

The webinar's ordering of value: L1 automates work; L2 adds *reliability*; L3 automates *continuous
system improvement* (the agent is embedded where work happens); L4 automates *improvement of the agent
itself*. Human-in-the-loop is a first-class primitive at **every** level, used where judgment adds value.

---

## 2. Current state — VERIFIED against the code (2026-07-23)

The #48 doc (2026-07-19) said "we have three of four loops, L2 is partial (no rubric grader)." **That is
now stale — L2 shipped.** Git-verified state:

| Loop | Status | Grounding (file · evidence) |
|---|---|---|
| **L1 Agent loop** | ✅ Mature | `deep/runner.py` (`execute_plan_once`, per-task specialist routing via `agent_type` + `worker_agent_type` override), `deep/orchestrator.py` (LangGraph `StateGraph`), `langchain/base.py` (`@tool` decorator framework, ADR 0003), `agents/__init__.py` (auto-discovery registry). Tool descriptions = method docstrings. |
| **L2 Verification** | ✅ **Shipped** (A/B) | **`deep/rubric.py`** = `deepagents.RubricMiddleware` (v0.6.12), grader `gpt-4o-mini`, `max_iterations ≤ 2`, grounded via `build_grader_verifier_tool`/`verify_suggestion_grounded`; gated by `DEEP_RUBRIC_MIDDLEWARE_ENABLED` + `agent_config["rubric_middleware"]`. **`deep/critic.py`** = hand-rolled `WorkerCritic` + `reflective_worker` fallback, `max_reflections=1`, per-agent `RUBRICS`, cheap `_is_agent_failure_summary` first gate. **Exactly one active per run** (`runner.py:365-401`), both scoped to `CRITIC_ENABLED_AGENTS = {triage_agent, optimization_agent}`. Verdicts → `run_metadata` → `DeepRun.state` (PRs #3 / #12 / #17). |
| **L3 Event-driven** | ✅ Native strength | `infrastructure/tasks/agent_tasks.py` (`run_ai_teammate_cycle`, beat-scheduled per workspace) → `application/services/detector_cycle.py` (`run_detector_cycle`, parallel detectors → `persist_finding_as_task`) → `dispatch_finding_specialist`. Online-eval feeder `perceived_error_scan.py` on the same cycle. |
| **L4 Hill-climbing** | 🟡 Substrate only | Trace substrate is real and dual: `DeepRunLog` (structured — system/user prompt, response, model, tokens, latency, cost + stamped rubric/critic verdicts) **and Langfuse v3** via `application/ports/tracing_port.py` → `infrastructure/adapters/tracing/langfuse.py` (`langfuse==3.15.0`, OTEL). Plus `AiActionDailyRollup` + weekly `eval_tasks.run_reviewer_feedback_eval`. **No agent reads these and proposes a gated harness change** — the loop is not closed. |

**Bottom line:** we are strong on L1/L2/L3 (L2 is arguably *ahead* of the reference — grounded,
tool-verified, dual-impl A/B). The one genuinely open loop is **L4**.

---

## 3. What the webinar adds that #48 didn't capture

1. **Precise `RubricMiddleware` runtime semantics** — these now describe *our* `deep/rubric.py`:
   `rubric` string on input state; **no rubric = no-op** (safe to always include); dedicated grader
   **sub-agent** that can call tools; per-criterion verdict with a **`gap`** (actionable feedback)
   re-prompted on revision; loops only on **`needs_revision`** up to `max_iterations` (**library
   default 3; we cap ≤2**); terminal statuses **`satisfied` / `max_iterations_reached` / `failed` /
   `grader_error`**; **`on_evaluation`** callback for telemetry; **attachable to sub-agents**
   specifically. → *Action A-1: confirm our `on_evaluation` → verdict-telemetry path emits all four
   terminal statuses (esp. `grader_error`) so a silently-erroring grader can't read as a pass.*
2. **Human-in-the-loop per loop level** (extends our `sign_off` gate): sensitive-tool approval (L1),
   **human-as-grader** (L2), output approval before a real mutation (L3), **harness-change review +
   green-eval gate** (L4). "Level 5" = auto-merge a harness change once it clears an eval threshold in
   an RL/eval env — aspirational, always gated for us.
3. **Closing L4 needs evals you trust** — the webinar's own caveat. Plus **eval-engineering**: when
   there's no ground truth, auto-generate eval cases from live traces + repo context and have a human
   curate. This is the missing enabler that makes L4's gate real.
4. **Memory split** — **procedural** (prompts/skills/tool descriptions = what L4 edits) vs **semantic**
   (user/relationship preferences = consolidated by a background job). Both are "the return arrow
   reaching inside the inner loop."
5. **Context-rot → prompt compression** for long/looping runs, plus hard guardrails (max cycles,
   timeouts) so a verification/reflection loop can't run away on cost. We have `ExecutionBudget`
   (`max_iterations`, `max_tasks`, `time_budget_seconds`) but **no compression of superseded attempts**.
6. **Cost/latency is the L2 dial** — every grader loop trades latency+cost for quality; use a cheaper
   worker model + strict grader, OR a stronger worker + lighter grader. We already do the former.

---

## 4. Actionable gap list (prioritized)

Each item: **what · where · why · rough effort · gate**. Ordered by value-per-unit-complexity.

### P0 — Close the L4 hill-climbing loop (self-improvement) — *the one open loop*
- **What:** an `AgentTraceQualityDetector` that reads `DeepRunLog` + stamped rubric/critic verdicts the
  same way `LogWatchErrorDetector` reads logs → deterministic aggregation of failure / low-score /
  fabrication patterns → files an evidence-bearing finding → routes (unchanged router, **+1
  `ROUTABLE_SOURCE_TYPES` entry**) to a new `harness_improvement_agent` that proposes a **prompt-version
  bump or tool fix**.
- **Where:** #48 Phase 3; reuses the #47 detector→router→specialist rails wholesale.
- **Why:** the webinar's highest-value loop; we have the substrate (§2 L4) and the rails — only the
  closing agent + gate are missing.
- **Effort:** M (one detector + one specialist + one enum entry + a prompt-registry write path).
- **Gate:** **never auto-promote.** Proposed change → `sign_off` approval **+ green offline eval**
  (`run_planner_eval`-style A/B) before the prompt/tool version flips. `IRREVERSIBLE` risk.

### P0 — Conclude the RubricMiddleware ↔ critic A/B; retire the loser
- **What:** run the eval A/B that #48 Phase 1 named as the ship criterion; record a verdict; **delete
  the losing path.** Two parallel verification impls is acceptable *only* as a time-boxed A/B (DRY /
  no-shortcuts — a second impl of one concern is the defect once the experiment concludes).
- **Where:** `deep/rubric.py` vs `deep/critic.py`; decision recorded in this doc + #48.
- **Why:** drift risk — a fix to one grader path that the other misses. The webinar frames rubric
  middleware as the target; keep it unless the A/B says otherwise.
- **Effort:** S–M (the harness exists; this is measurement + a deletion PR).
- **Gate:** the A/B metric must actually move finding quality, else neither ships universally.

### P1 — Pick the L4 aggregation source: `DeepRunLog` vs Langfuse (both exist)
- **What:** decide which trace store the P0 `AgentTraceQualityDetector` aggregates over. **Both are
  wired** (verified 2026-07-23): `DeepRunLog` (structured, in-DB, carries stamped rubric/critic
  verdicts — ideal for deterministic aggregation) and **Langfuse v3** via `tracing_port.py` /
  `adapters/tracing/langfuse.py` (rich cross-run/session spans). Recommendation: **aggregate over
  `DeepRunLog`** (verdicts already live there, no external round-trip), use Langfuse for human trace
  inspection + the eval-engineering feeder (P1 below).
- **Where:** `infrastructure/persistence/ai/agents/models.py::DeepRunLog`; `application/ports/tracing_port.py`.
- **Why:** L4 aggregates over traces — pick the source of truth deliberately before building the
  detector, don't straddle both.
- **Effort:** S (a decision + a short ADR/note; no new plumbing — the substrate exists).
- **Gate:** none — decision.

### P1 — Eval-engineering: auto-generate eval cases from traces (the L4 gate enabler)
- **What:** a management command / flow that turns real `DeepRunLog` traces (esp. perceived-error and
  low-verdict runs) + finding context into candidate eval cases for human curation into the dataset.
- **Where:** extends `eval_tasks` + the prompt-eval suite; feeds the P0 gate.
- **Why:** L4 can't merge safely without evals; security triage has weak ground truth → generate+curate.
- **Effort:** M.
- **Gate:** human curates every generated case before it enters the dataset.

### P2 — Reflection memory (Reflexion long-term) — #48 Phase 2
- **What:** a bounded, curated `ReflectionStore` keyed by `agent_type`; after a low-scored run, distill
  one lesson and inject top-K into that agent's next system prompt. Procedural memory (per the split).
- **Why:** compounds L2 — the critic's `gap` feedback is the raw material for distilled reflections.
- **Effort:** M. **Gate:** advisory context only — can never override role/risk gates (ADR 0002 / SEE-203).

### P2 — Expand rubric coverage beyond `{triage, optimization}` as criteria firm up
- **What:** add rubrics for `report_agent` / cloud-posture specialists **only where criteria are clear
  and verifiable**; keep the deterministic-first-gate discipline.
- **Why:** verification only helps where success is checkable — the LLM-as-judge fit test.
- **Effort:** S per agent. **Gate:** each addition ships with an eval showing it moves quality.

### P2 — Wire harness-change proposals through `sign_off` (the L4 HITL primitive)
- **What:** the P0 specialist's output is a proposed harness change → `components/sign_off` approval
  surface + green-eval gate before merge. Lands with P0.
- **Why:** prompt/tool changes are irreversible for live behaviour; HITL is mandatory here.
- **Effort:** S (reuse `sign_off`). **Gate:** is the gate.

### P3 — Context-rot guardrails for long deep runs
- **What:** compress superseded worker attempts (keep current artifact + rubric criteria + goal), and
  keep the hard `ExecutionBudget` cycle/timeout caps as the runaway backstop.
- **Why:** cost/latency control as verification+reflection loops deepen.
- **Effort:** M. **Gate:** none — a cost optimization, verify it doesn't drop needed context.

### P3 — Durable resume (reliability substrate under L3/L4)
- **What:** adopt the LangGraph checkpointer so a worker that dies mid-run resumes instead of
  restarting. Designed, not adopted (also a wanjala §14.4 gap).
- **Why:** autonomous/scheduled runs (L3) and long L4 analyses need crash-safety.
- **Effort:** M. **Gate:** none.

---

## 5. Discipline (what we deliberately will NOT do)

- **No reflection/verification on every agent** — only where criteria are clear *and* improvement is
  *measured*. A loop that doesn't move an eval metric is deleted.
- **No unbounded iterations** — hard cap `≤2`; the 3rd pass isn't worth the latency/cost.
- **No auto-promotion of prompt/tool changes** — human `sign_off` + green eval, always.
- **No new orchestration framework** — everything above is nodes/edges on the existing LangGraph
  orchestrator + detectors on the existing cycle (the #47 scale proof, reused).
- **No two permanent impls of one concern** — the rubric/critic A/B concludes and one path is deleted.

---

## 6. Skill / knowledge propagation

The generic four-loop framework + `RubricMiddleware` runtime semantics + HITL-per-level + memory/
eval-engineering/context-rot notes were added to the shared **wanjala `agents` skill §14.10** ("third
lens — Loop engineering") so both codebases share the vocabulary. Auto-sec-specific "we shipped it"
facts stay here (auto-sec is where L2 is live and where L4 will be closed).
