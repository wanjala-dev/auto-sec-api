# Loop Engineering & Self-Improvement — Mapping onto the Auto-Sec Deep Pipeline

**Status:** Research + design (no code yet). Ticket: #48.
**Date:** 2026-07-19.

This maps two bodies of work — LangChain's *loop engineering* ("loopcraft") and the
*Reflexion / evaluator-optimizer* self-improvement patterns — onto Auto-Sec's existing
deep-agent pipeline, and proposes a phased path to fold them in **without** re-architecting.

The headline finding: **we already have three of the four loop levels, and the log-watch →
optimization pipeline we just shipped is a working example of the fourth.** Self-improvement is
not a new system — it's the *same detector → analysis-agent → gated-change loop*, pointed at a
new subject (the agents' own traces instead of the platform's logs).

---

## 1. The frameworks (sources)

**Loop engineering — the four-level model** ([LangChain, "The Art of Loop Engineering"](https://www.langchain.com/blog/the-art-of-loop-engineering)):

| Level | Loop | What it does |
|---|---|---|
| **L1 — Agent loop** | model calls tools in a loop until done | the ReAct primitive |
| **L2 — Verification loop** | a grader checks output against a rubric; on fail, sends it back **with feedback** | quality gate |
| **L3 — Event-driven loop** | agents fire off webhooks / cron / triggers, not manual calls | runs as infrastructure |
| **L4 — Hill-climbing loop** | analyze production **traces** → auto-rewrite prompts/tools | self-improvement |

The key architectural move: *"the return arrow doesn't just loop back to the top — it reaches
inside and updates the inner loop directly."* Each outer cycle makes the inner loops better.

**Reflexion** (Shinn et al., NeurIPS 2023) — verbal reinforcement learning: an agent reviews its
own trajectory, distills a **reflection**, and stores it. **Short-term memory** = the current
attempt's trajectory; **long-term memory** = distilled reflections re-injected on the next attempt.

**Evaluator-optimizer** ([Anthropic, "Building Effective Agents"](https://www.anthropic.com/engineering/building-effective-agents))
— one LLM generates, another evaluates and gives feedback, in a loop. Use it **only** when (a)
there are clear evaluation criteria and (b) responses demonstrably improve with feedback.

**The discipline that bounds all of this** (both sources agree):
- Returns diminish sharply after **2–3 reflection iterations** (iter 1 catches ~60% of errors,
  iter 2 ~25%, iter 3 ~5%). Cap reflection at **1–2 passes**.
- *"Add complexity only when it demonstrably improves outcomes."* Agents trade latency + cost for
  quality; a reflection loop that doesn't measurably help is pure cost.
- Optimizing the **tool/agent-computer interface** usually beats optimizing the prompt.

---

## 2. What we already have (grounded in the code)

| Loop level | Status | Where |
|---|---|---|
| **L1 Agent loop** | ✅ Have | ReAct workers via `create_agent_executor`; LangGraph orchestrator (`deep/orchestrator.py`) |
| **L2 Verification** | 🟡 Partial | **Honesty guard** (`_is_agent_failure_summary`, `_format_honest_failure_answer`) is a *deterministic* fabrication check; **synthesizer replan** (`replan_requested: yes`, `max_replans=1`) is a coarse plan-level retry. **No per-output rubric grader.** |
| **L3 Event-driven** | ✅ Have (strength) | The detector cycle (`run_detector_cycle`, beat-scheduled) + `AiFindingRouterDetector`. Most systems bolt L3 on last; ours is native. |
| **L4 Hill-climbing** | 🟡 Substrate only | Prompt registry (`infrastructure/prompts/registry.py`, versioned YAML), offline evaluators (`run_planner_eval` / `run_feedback_eval` / `run_writing_eval`), `promote_feedback_to_dataset`, Langfuse tracing (`tracing/langfuse.py`), `replay_conversation`. **No closing loop** that reads traces → proposes a change → gates promotion. |

Budget primitives already exist: `ExecutionBudget` (`max_iterations`, `max_tasks`,
`time_budget_seconds`, `max_worker_failures`) — the scheduler routes to the synthesizer when any is
exceeded. A reflection cap slots in here as `max_reflections`.

### The insight that ties it together

**The log-watch → optimization pipeline we just built (#47) IS an L3+L4 hill-climbing loop.**
Its shape is:

```
traces (platform logs) → deterministic aggregation (LogPatternAnalyzer)
   → analysis agent (optimization_agent) → recommendation to improve the harness
   → [today: surfaced on the board for a human] 
```

That is *exactly* Level 4 — just pointed at the **platform's operational logs** instead of the
**agents' own execution traces**. Point the same machinery at Langfuse/DeepRun traces and the
recommendation becomes "bump this agent's prompt version / fix this tool" — **agent
self-improvement, built from parts we already have.** This is the scaling path Henry asked for:
*"log-watch findings go back to the orchestrator/planner to feed the triage agent — make sure this
expands and scales."* It does, because L4 self-improvement is the same loop with a new detector +
a new specialist + one `ROUTABLE_SOURCE_TYPES` entry (the #47 scale proof, reused).

---

## 3. Proposed phases

Ordered by value-per-unit-complexity. Each phase is independently shippable and independently
useful — no phase is a throwaway stepping stone (per `no-shortcuts.md`).

### Phase 1 — Verification loop (L2): a bounded critic node — *highest near-term value*

Add an **optional** `critic_fn` to `build_orchestrator`, evaluated after a worker completes and
before the result is accepted. It grades the `WorkerResult` against a **per-agent rubric**
(evidence cited? grounded in the finding payload? not fabricated? recommendation actually addresses
the signal?). On fail, it sends the task back to the **same worker** with the critique appended —
Reflexion at the task level — capped at **`max_reflections=1`** (the diminishing-returns cap).

- Reuse the deterministic **honesty guard** as the *cheap first gate* (no LLM); only spend an LLM
  critic when the honesty guard passes but the rubric might still fail. (Anthropic: don't add LLM
  cost unless it demonstrably helps.)
- SOC payoff: the critic grades *"did triage/optimization actually address the evidence?"* —
  directly lifts finding quality, which is the product.
- Fits the graph as one conditional edge; bounded by `ExecutionBudget`. **Only wire it for agents
  with clear rubrics** (triage, optimization) — not universally.

**Ship criterion:** an A/B on the eval set (`run_planner_eval`-style) shows the critic measurably
raises finding quality. If it doesn't, we don't ship it — that's the evaluator-optimizer fit test.

### Phase 2 — Reflection memory (Reflexion long-term memory)

A curated, **bounded** `ReflectionStore` keyed by `agent_type`: after a low-scored or failed run,
distill one lesson (*"for ImportError log lines, name the missing symbol in the fix"*) and store
it. Inject the top-K relevant reflections into that agent's system prompt on the next run — the
"return arrow reaches inside the inner loop." Curated + capped (not unbounded growth), and the
distillation itself is gated so garbage lessons don't accumulate.

- Builds on the existing conversation-memory layer + prompt registry.
- Guardrail: reflections are advisory context, never authority — they can't override role/risk
  gates (ADR 0002 / SEE-203 still hold).

### Phase 3 — Hill-climbing loop (L4): self-improvement over agent traces — *reuses #47 wholesale*

A new detector `AgentTraceQualityDetector` that reads DeepRun/eval/Langfuse traces the **same way**
`LogWatchErrorDetector` reads logs: deterministic aggregation of failure / low-score / fabrication
patterns → files an **evidence-bearing** finding → routes (via the *unchanged* router, +1
`ROUTABLE_SOURCE_TYPES` entry) to a new `harness_improvement_agent` specialist → which proposes a
**prompt-version bump or tool fix**, validated **offline** by `run_planner_eval` before anything
changes.

- **Never auto-promote.** A prompt/tool change is effectively irreversible for live behaviour →
  `ToolRisk.IRREVERSIBLE` → the SEE-203 risk gate requires human approval + a green eval gate. The
  evaluator (offline eval) + human sign-off = *safe* self-improvement. This is the whole reason the
  prompt registry + evaluators already exist — Phase 3 just closes the loop between them.
- This literally realizes *"findings go back to the orchestrator/planner"*: agent-trace findings
  ride the same detector → router → specialist rails, and the specialist's output is a validated,
  gated harness change.

### Phase 4 — The meta-loop (make L3 drive L2 and L4)

Nothing new to build — just recognize that the **detector cycle (L3) is the clock** that drives
per-run verification (L2) and periodic hill-climbing (L4). The **provenance trail** we shipped in
#50 becomes the trace substrate the L4 detector aggregates over (which agent acted, when, with what
confidence, and — post-Phase-1 — what the critic scored).

---

## 4. What we deliberately will NOT do (the discipline)

- **No reflection on every agent.** Only where criteria are clear and improvement is *measured*
  (triage, optimization, planner). A reflection loop that doesn't move an eval metric is deleted.
- **No unbounded iterations.** Hard cap at `max_reflections ≤ 2`; the third pass isn't worth the
  latency/cost.
- **No auto-promotion of prompt/tool changes.** Human + eval gate, always (SEE-203).
- **No new orchestration framework.** Everything above is nodes/edges on the *existing* LangGraph
  orchestrator + detectors on the *existing* cycle. If a phase needs a new framework, that's a
  signal the design is wrong.
- **Optimize tools before prompts.** Per Anthropic's SWE-bench experience, the agent-computer
  interface (tool descriptions, `ToolResult` shapes) is usually the higher-leverage fix — the
  critic (Phase 1) should be allowed to flag *tool* problems, not just prompt problems.

---

## 5. Suggested sequencing

1. **Phase 1 (critic node)** — highest value, smallest surface, directly lifts finding quality.
   Gate on an eval A/B before shipping.
2. **Phase 3 (trace hill-climbing)** — reuses #47's rails; big strategic payoff (the platform
   improves its own agents), fully human-gated so it's safe to build early.
3. **Phase 2 (reflection memory)** — compounds Phase 1 (the critic's critiques are the raw material
   for distilled reflections).
4. **Phase 4** — falls out for free once 1 + 3 exist.

Relates to: #45 (runner retry/budget — `max_reflections` lives with the budget work), #46 (online
eval / cost caps — the eval gate for Phase 3), #52 (async dispatch — the L4 detector shouldn't
block the cycle either).
