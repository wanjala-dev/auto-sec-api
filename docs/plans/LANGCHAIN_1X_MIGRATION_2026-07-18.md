# LangChain 0.3 → 1.x Migration (unlock `deepagents.RubricMiddleware`)

**Date:** 2026-07-18
**Track:** Track 2 (dep + core-worker migration). Track 1 is hardening the hand-rolled
verification loop on the current 0.3 stack; the two converge when we swap
`deep/critic.py`'s `WorkerCritic` / `reflective_worker` for the real
`RubricMiddleware` once 1.x lands.
**Status:** EXECUTED 2026-07-19 on branch `feat/langchain-1x-migration` (Phases 1-6 landed;
verified in a fresh python:3.12 venv — see the branch commits). Corrections found at
execution time vs this plan: (a) `RubricMiddleware` takes NO `rubric` kwarg — the rubric
rides the *invocation state* (`state["rubric"]`; no rubric = no-op) and `model` is REQUIRED;
(b) memory replacement shipped as SQL-history threading into the `create_agent` input
(handle-level `history_provider`), NOT a checkpointer — a process-local saver would fork
conversations per worker; (c) `langchain-classic` added for `ConversationalRetrievalChain`;
(d) langgraph-checkpoint 4.x serde is typed-only (`dumps_typed`/`loads_typed`) — the
DatabaseSaver stores type tags beside the blobs; (e) langfuse 2.48's LC handler does NOT
load under core 1.x (R2 confirmed) — tracing degrades to NullTracingAdapter until the 3.x bump.

---

## 0. Why

`deepagents.RubricMiddleware` (grader-with-tools self-evaluation loop) is the quality
lever we want for the SOC agents — it grades each worker answer against a rubric and
re-runs until it passes, and crucially its grader can **carry tools** for grounded
verification instead of grading on vibes. `RubricMiddleware` is only available through
`deepagents`, which is built on the LangChain 1.x `create_agent` middleware system. Our
worker is on the **legacy** `langchain.agents.AgentExecutor` + `create_react_agent` API
that LangChain 1.0 removed. So: migrate to 1.x first, then adopt `RubricMiddleware`.

---

## 1. Target versions (mutually compatible, verified on PyPI 2026-07-18)

`deepagents` is the constraint driver. `deepagents 0.6.12` `requires_dist`:

```
langchain          <2.0.0,>=1.3.11
langchain-core     <2.0.0,>=1.4.8
langchain-anthropic<2.0.0,>=1.4.7
langchain-google-genai <5.0.0,>=4.2.5   (pulled in transitively; we don't use Gemini yet)
langsmith          >=0.8.11
wcmatch            >=10.1
```

Resolving the rest of the stack to the newest 1.x that satisfies those bounds:

| Package | Current (0.3 stack) | **Target pin (1.x)** | Constraint source |
|---|---|---|---|
| `langchain` | `0.3.25` | `==1.3.14` | deepagents `>=1.3.11`; latest 1.3.x |
| `langchain-core` | `0.3.83` | `==1.4.9` | langchain 1.3.14 `>=1.4.9`; deepagents `>=1.4.8`; openai/langgraph `>=1.4.9`/`>=1.4.7` |
| `langchain-community` | `0.3.24` | `==0.4.x` (latest 0.4 line) | 1.x-core-compatible community line; **verify** exact at pip-resolve time |
| `langchain-text-splitters` | `0.3.8` | `==1.0.x` | 1.x line paired with core 1.x |
| `langchain-openai` | `0.3.17` | `==1.3.5` | latest 1.x; **requires `openai>=2.45.0`** (see risk R1) |
| `langchain-anthropic` | *not installed* | `==1.4.7` (or newer 1.4.x) | deepagents `>=1.4.7`; **new dependency** |
| `langgraph` | `>=0.2.76,<0.3` | `==1.2.9` | latest 1.2.x; `langchain-core>=1.4.7` |
| `langgraph-checkpoint` | `>=2.1.2,<3` | `>=4.1.0,<5` | langgraph 1.2.9 `>=4.1.0` |
| `deepagents` | *not installed* | `==0.6.12` | the feature we're unlocking |
| `langsmith` | `>=0.1.125,<0.4` | `>=0.8.11,<0.9` | deepagents `>=0.8.11` (widens the current cap — **breaking bump**) |
| `openai` | `1.109.1` | `>=2.45.0` | **transitively forced** by langchain-openai 1.3.5 (see R1) |
| `langfuse` | `2.48.0` | **verify 1.x-core compat** | tracing callback; may need a 3.x bump (see R4) |

> **Pin discipline:** pin `langchain`, `langchain-core`, `langchain-openai`, `langchain-anthropic`,
> `langgraph`, `deepagents`, `openai` to exact versions. Let `langchain-community`,
> `langchain-text-splitters`, `langgraph-checkpoint`, `langsmith` float within the
> compatible line and freeze the resolved set from a clean `pip install` into base.txt.
> **These are the highest-published 1.x versions as of 2026-07-18 — re-resolve at
> execution time; the ecosystem moves weekly.**

---

## 2. `AgentExecutor` + `create_react_agent` → `create_agent` mapping (our decorator framework)

The decorator framework (`@register_agent`, `@tool`, `@requires_role`, `ToolResult`,
`BaseAgent`) is the public authoring API (ADR 0003) and **stays intact**. The migration
changes the *implementation under it*, not the ~9 agent files.

### 2.1 What carries over unchanged (the load-bearing insight)

- **Tools.** `_setup_tools` already promotes `@tool` methods to
  `langchain_core.tools.StructuredTool` / `Tool` instances (base.py ~L733). `create_agent`
  takes exactly those — a `Sequence[BaseTool]`. **No tool rebuild, no tool-name change.**
  Tool-name byte-stability (the DB `Agent.config.custom_profile.tool_whitelist` references
  tools by string) is preserved because `meta["name"]` → `StructuredTool.name` is untouched.
- **`@requires_role` gating.** It wraps the *Python method body* (base.py ~L221) and runs
  inside `tool.func` — orthogonal to which executor calls the tool. Unchanged.
- **`@register_agent` / `AgentRegistry` / auto-discovery.** Class-definition-time; no LangChain
  surface. Unchanged.
- **`self.llm`.** `llm_port.get_llm(...)` returns a `BaseChatModel` (ChatOpenAI). `create_agent`
  accepts a `BaseChatModel` **instance** directly for `model=`, so the provider port
  abstraction is preserved — we do NOT convert to a `"provider:model"` string.
- **The tool-whitelist filter** (`_apply_run_context_tool_policy` / `_apply_custom_profile_tool_whitelist`,
  ~L1182) mutates `self.tools` then calls `self._create_agent_executor()` to rebuild. Since
  `create_agent` takes `tools=self.tools`, the rebuild-on-filter pattern is identical — only
  the builder body changes.

### 2.2 What changes — inside `_create_agent_executor` (base.py ~L886–1055)

| Legacy (0.3) | 1.x (`create_agent`) |
|---|---|
| `create_tool_calling_agent(llm, tools, prompt)` → `AgentExecutor(agent=…, tools=…, memory=…, …)` | `agent = create_agent(model=self.llm, tools=self.tools, system_prompt=self._build_system_message(), middleware=[…], checkpointer=saver)` |
| `create_react_agent(llm, tools, prompt)` fallback | **dropped** — `create_agent` IS a tool-calling graph. The ReAct prose-format fallback (and all its parse-error scaffolding: `handle_parsing_errors`, `early_stopping_method="force"`, the `return_stopped_response` monkeypatch) is deleted. Native tool-calling has no prose parser to fail. |
| `ChatPromptTemplate.from_messages([system, human, MessagesPlaceholder("agent_scratchpad")])` | `system_prompt=` string arg. No scratchpad placeholder — the graph manages the message list. |
| `PromptTemplate` ReAct template (`_create_prompt_template`) | **deleted** (fallback gone). |
| `memory=self.memory` (`ConversationBufferMemory`-style) + `_patch_memory_conversation_id` + `_patch_langchain_memory` | `checkpointer=` + `config={"configurable": {"thread_id": conversation_id}}` at invoke. The two conversation-id monkeypatches are **deleted**; correctness moves to using the memory service's conversation_id AS the checkpointer thread_id. |
| `max_iterations`, `max_execution_time`, `return_intermediate_steps=True` on `AgentExecutor` | recursion/step caps via middleware (`ModelCallLimitMiddleware` / a custom step-cap middleware); the message transcript IS the intermediate-step record (no `return_intermediate_steps` flag). |
| `callbacks=[telemetry, tracing]` on the executor | passed via `config={"callbacks": […]}` at invoke, or attached to `self.llm` (langchain-core callbacks still work on the model). |

### 2.3 Invocation contract adaptation — `_invoke_agent_executor` (base.py ~L1448)

`execute()` calls `self._invoke_agent_executor({"input": query})` and reads
`result["output"]` (L1698) + `result["intermediate_steps"]` (L1679). We **keep that
contract** and adapt inside the seam:

- **Input:** `{"input": q}` → `{"messages": [{"role": "user", "content": q}]}`.
- **Invoke:** `graph.invoke(state, config={"configurable": {"thread_id": conv_id}, "callbacks": cbs})`.
- **Output → `output`:** `result["messages"][-1].content`.
- **Output → `intermediate_steps`:** reconstruct `[(AgentAction-like, observation)]` pairs by
  walking the returned messages for `AIMessage.tool_calls` paired with the following
  `ToolMessage.content`. `_persist_tool_observations` (L2004) already unpacks
  `step[0], step[1]` defensively and tolerates shape drift — we feed it `(SimpleNamespace(tool=…, tool_input=…, log=…), observation)` tuples so DeepRunLog telemetry keeps working.

**This adaptation is why the migration is test-safe:** `AgentTestCase` patches
`_create_agent_executor` to a no-op and installs a `_ScriptedExecutor` on
`agent.agent_executor` whose `.invoke({"input": q})` returns `{"output": …}`. As long as
`_invoke_agent_executor` still routes through `self.agent_executor.invoke(inputs)` **when
the executor is the scripted stub**, existing agent unit tests pass untouched. The spike
keeps `self.agent_executor` as the invocation handle and branches on graph-vs-legacy so
the harness seam is preserved.

### 2.4 Middleware list on `create_agent` (foundation for RubricMiddleware)

`create_agent(..., middleware=[...])` is where 1.x expresses cross-cutting concerns. Order:
1. A **step-cap middleware** (replaces `max_iterations` / `max_execution_time`).
2. Telemetry/tracing as `AgentMiddleware` hooks (or keep them as invoke-time callbacks initially — lower risk).
3. **`RubricMiddleware`** — added in the convergence phase (Phase 6), see §7.

---

## 3. langgraph 0.2 → 1.x changes in `deep/orchestrator.py` + `runner.py`

The deep orchestrator does NOT use `create_react_agent` — it builds a bespoke `StateGraph`
whose nodes are plain Python callables (`planner_fn`, `worker_fn`, `synthesizer_fn`). So this
is **API-surface migration**, not a rewrite. Concrete deltas:

| Area | 0.2 | 1.x |
|---|---|---|
| `Send` import | `from langgraph.constants import Send` | `from langgraph.types import Send` (constants path removed in 1.x; **verify** — some 1.x keep a shim). Fan-out (`[Send("worker", {"task": t}) for t in ready]`, orch L510) semantics unchanged. |
| `StateGraph` / `START` / `END` | `from langgraph.graph import END, START, StateGraph` | same import path; **`.compile()` return type & config keys** need a check. `add_conditional_edges(node, fn, path_map)` unchanged. |
| `interrupt` (HITL) | `from langgraph.types import interrupt` (already the 0.2 path, orch L29) | same module; **resume semantics changed**: 1.x uses `Command(resume=…)` first-class. runner.py L455–456 explicitly notes "in langgraph 0.0.69 explicit `Command(resume=…)` is not available; reuse the same thread_id" — 1.x REPLACES that workaround with real `Command(resume={"approved": True})`. This is the one place that gets *better* AND needs real rework. |
| Checkpointer | `checkpoints.py` imports `langgraph.checkpoint.base` / `.memory.MemorySaver` with a `langgraph_checkpoint.*` fallback | 1.x: `langgraph.checkpoint.memory.InMemorySaver` (MemorySaver aliased). The DatabaseSaver (Postgres) path needs its `langgraph-checkpoint>=4.1` API re-checked (serde + `put`/`get_tuple` signatures shifted across the 2.x→4.x checkpoint line). |
| `Command(goto=…)` | referenced in runner comments (L168, L330) | first-class in 1.x; can replace the "sentinel worker" force-route hack. |

**Effort:** orchestrator/runner is ~2 files of real work — mostly import moves + rewriting
the HITL resume around real `Command(resume=…)`, plus a checkpointer serde re-verify. The
node bodies (budget checks, scheduler, dependency resolution) are pure Python and untouched.

---

## 4. File-by-file impact (36 files under `components/agents/` touch legacy LC/LG APIs)

Grouped by change type (counts from `grep -rlnE` on 2026-07-18):

### Group A — mechanical import rename (low risk, ~half a day total)
- `from langchain.tools import StructuredTool, Tool` (5 files) → `from langchain_core.tools import …`
- `from langchain.schema import …` (14 files) → `from langchain_core.messages import HumanMessage/AIMessage/…` (langchain.schema was already a re-export shim; 1.x removes it).
- `from langchain.prompts import …` (1 file: base.py) → drop (system_prompt string) or `langchain_core.prompts`.
- `pydantic_v1` (1 file) → `pydantic` v2 (deepagents/langchain 1.x are pydantic-v2-native; the v1 shim is gone). base.py already has a v2-first `try/except` for this.
- `from langgraph.constants import Send` → `from langgraph.types import Send` (verify).

### Group B — real rework (the core; ~3–5 days)
- **`langchain/base.py`** — `_create_agent_executor`, `_invoke_agent_executor`, `_create_chat_prompt_template`/`_create_prompt_template` (delete), the two memory monkeypatches (delete), `_persist_tool_observations` feed (adapt tuple shape). **This is the spike.**
- **`langchain/graph_agent.py` (`build_graph_executor`)** — the opt-in `use_langgraph` StateGraph executor; re-point to 1.x StateGraph or replace with `create_agent`.
- **`deep/orchestrator.py`** — Send/checkpointer/interrupt (see §3).
- **`deep/runner.py`** — HITL resume via real `Command(resume=…)` (see §3).
- **`deep/checkpoints.py`** — checkpointer serde against `langgraph-checkpoint>=4.1`.
- **`memories/` + `memory_service.py` + `memory_adapter.py`** (`ConversationBufferMemory`, 5 files) — `ConversationBufferMemory` is removed in 1.x. Replace the memory abstraction with checkpointer-backed threads (thread_id = conversation_id). This is the largest single behavioural change and needs its own phase.

### Group C — tests (adapt harness + per-agent tests)
- `agent_test_case.py` — the `_ScriptedExecutor` seam is preserved by the spike, but add a second scripted shape that mimics `{"messages": […]}` for tests that want to exercise the real adapter.
- Per-agent unit tests under `components/agents/tests/unit/` and `tests/` — run each; fix any that assert on `intermediate_steps` tuple internals or ReAct-specific behaviour.

---

## 5. Risk assessment

| ID | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | `langchain-openai 1.3.5` forces **`openai>=2.45.0`** — a MAJOR openai-SDK bump. Any direct `openai` SDK usage elsewhere in the repo (embeddings, direct completions, the knowledge context) can break on the 1.x→2.x SDK change. | **High** | `grep -rn "import openai\|from openai"` across the whole repo BEFORE upgrading; migrate direct call sites to the openai 2.x SDK. This is the biggest hidden blast radius. |
| **R2** | `langfuse 2.48.0` tracing callback may not be langchain-core-1.x compatible (its LC callback handler targets core 0.x/0.3). | Medium | Verify langfuse ↔ core-1.x; likely need langfuse 3.x. The tracing is behind `TracingPort` (NullTracingAdapter fallback), so it degrades gracefully — not a blocker for the spike. |
| **R3** | `ConversationBufferMemory` removal changes memory semantics (buffer → checkpointer threads). The two conversation-id monkeypatches exist because the old memory drifted conversation_ids; the checkpointer thread_id model must preserve the same correctness. | Medium | Dedicated memory phase (§6 Phase 3) with the existing memory-service tests as the guard. thread_id := memory_service.get_conversation_id(). |
| **R4** | Checkpoint serde format changed across `langgraph-checkpoint` 2.x→4.x; existing persisted DatabaseSaver rows may be unreadable. | Medium | Deep-run checkpoints are ephemeral/short-lived (in-flight runs). Drain in-flight runs before deploy; no long-term migration of checkpoint rows needed. |
| **R5** | `create_agent`'s native tool-calling has **no ReAct prose fallback** — models without function-calling break. | Low | All configured models (gpt-4o-mini, claude) support native tool-calling. The `use_react_agent` config escape hatch is dropped; document it. |
| **R6** | Transitive resolver conflicts (community/text-splitters/langsmith cap widening `<0.4`→`>=0.8`). | Medium | Resolve in a clean venv, freeze the exact set; don't hand-pin the floaters. |
| **R7** | Can't verify the upgraded deps in `auto_sec-web-1` (old deps baked in, mounts primary clone not this tree). | — | Verify in a throwaway venv/image; state honestly what's unverified (see spike report). |

---

## 6. Phased, independently-verifiable migration sequence

Each phase is independently testable and shippable behind the fact that 0.3 and 1.x are
mutually exclusive installs — so phases are branch-staged, not runtime-toggled.

**Phase 0 — Recon (0.5 day).** `grep` the whole repo for direct `openai` SDK usage (R1),
langfuse LC-callback usage (R2), and every legacy import. Produce the exact call-site list.
*Verify:* the list is complete; no surprises.

**Phase 1 — Dep pins + clean resolve (0.5 day).** Update `requirements/base.txt` to the §1
pins; `pip install` in a clean venv; freeze the resolved floaters. *Verify:* the resolver
produces a conflict-free set; `python -c "import langchain, deepagents; from langchain.agents import create_agent; from deepagents.middleware.rubric import RubricMiddleware"` succeeds. **(Spike does the pin edits.)**

**Phase 2 — Core worker on `create_agent` (2 days). ← THE SPIKE.** Migrate
`_create_agent_executor` + `_invoke_agent_executor` in base.py; delete ReAct fallback +
prompt templates + memory monkeypatches; adapt the output→(output, intermediate_steps)
seam. *Verify:* `agent auto-discovery` imports clean; ONE agent's `AgentTestCase` unit tests
pass in the 1.x venv.

**Phase 3 — Memory as checkpointer threads (1.5 days).** Replace `ConversationBufferMemory`
usage in `memories/` + `memory_service.py`; thread_id := conversation_id. *Verify:*
memory-service tests green; a two-turn conversation retains context.

**Phase 4 — Deep orchestrator/runner on langgraph 1.x (2 days).** Send/checkpointer/interrupt
import moves; HITL resume via real `Command(resume=…)`; checkpoint serde re-verify. *Verify:*
`deep/` tests green; a fan-out run with an approval gate pauses+resumes.

**Phase 5 — Import sweep + openai 2.x + langfuse (1.5 days).** Group-A mechanical renames
across the remaining files; migrate direct openai call sites (R1); bump langfuse (R2).
*Verify:* full `components/agents/` test suite green; architecture tests green.

**Phase 6 — Convergence: adopt `RubricMiddleware` (1 day).** See §7. *Verify:* a graded
worker re-runs on a confident fail and passes; grounded-verification tools are called by the
grader.

**Total estimate: ~11–12 engineer-days** (excludes R1 openai-SDK blast radius if it's large —
that could add 1–3 days depending on how many direct call sites exist repo-wide).

---

## 7. Hand-rolled critic → `RubricMiddleware` (the convergence)

`deep/critic.py` already reads like a hand-rolled RubricMiddleware — this mapping is
deliberate and clean:

| `deep/critic.py` (hand-rolled) | `deepagents.RubricMiddleware` |
|---|---|
| `RUBRICS` dict (per-agent-type checklists, L57) | the `rubric` string passed at invoke time (per run), or a middleware built per agent-type |
| `WorkerCritic._SYSTEM` grading prompt (L71) | `RubricMiddleware(system_prompt=…)` |
| `WorkerCritic.grade(...)` LLM call returning `{passed, score, feedback}` | the middleware's internal grader sub-agent returning `RubricEvaluation` |
| `_GRADER_MODEL` (cheap grader tier, L51) | `RubricMiddleware(model=…)` |
| `reflective_worker(..., max_reflections=1)` bounded re-run loop (L198) | `RubricMiddleware(max_iterations=…)` (default 3, cap 20) — re-injects grader feedback as a HumanMessage and resumes the agent loop |
| `_CONFIDENT_FAIL_FLOOR` / "only re-run confident fails" heuristic (L45; Huang et al. ICLR 2024) | encode in the grader `system_prompt` (grader returns `satisfied` on marginal fails) or the `on_evaluation` callback |
| `_is_agent_failure_summary` deterministic pre-gate (L126) | keep as a fast pre-check OR a grader tool that inspects the transcript |

**The key quality lever — the grader MUST carry TOOLS.** `RubricMiddleware.tools=[...]` lets
the grader call verification tools (e.g. `run_test_suite`, or our `retrieve_workspace_context`
/ the finding-evidence lookup) to check groundedness against real data **before** producing a
verdict, instead of grading abstractly. Our current critic grades on the LLM's read of the
answer text alone (`critic.py` L143 — answer string only, no tool access); `finding_verifier.py`
enforces hard groundedness deterministically *separately*. Adopting `RubricMiddleware` with
`tools=[<evidence-lookup tools>]` **unifies** those two: the grader itself verifies against
evidence. That is the single biggest quality improvement of the whole migration — carry it in
the convergence phase, don't ship a tool-less RubricMiddleware.

**Convergence order:** keep `WorkerCritic`/`reflective_worker` running through Phases 1–5
(Track 1 hardens it in parallel). In Phase 6, attach `RubricMiddleware` to the `create_agent`
workers with `tools=` wired to the evidence lookups, port the `RUBRICS` strings across, then
delete `reflective_worker` (leaving `finding_verifier.py`'s deterministic gate as belt-and-braces).

---

## 8. What the spike does / doesn't cover

**Does:** §1 dep pins in `requirements/base.txt`; the Phase-2 core-worker migration in
`base.py` (`create_agent` construction + invocation seam), keeping the `AgentTestCase` seam
and tool-name byte-stability intact.

**Doesn't:** Phases 3–6 (memory, deep orchestrator, import sweep, RubricMiddleware). See the
spike report for the honest verification status.
